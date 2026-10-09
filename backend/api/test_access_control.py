"""Smart room access control: rooms, permissions, unlocking and access history."""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .door_hardware import DoorGateway
from .models import (AccountProfile, Business, Contract, Employee, Room, RoomAccessAttempt, RoomAccessGrant,
                     RoomPermissionChange, SimulatedDoor)
from .onboarding import purge_employee
from .platform import purge_business

FAKE_GATEWAY = "api.test_access_control.FakeGateway"


class FakeGateway(DoorGateway):
    """Stands in for door hardware in tests only."""

    def device_status(self, room):
        return "online"

    def verify_proximity(self, room, user, method, proof):
        return proof == f"tag-{room.door_identifier}"

    def unlock(self, room, user):
        if room.door_identifier == "broken":
            raise ConnectionError("controller offline")
        return None if room.door_identifier == "silent" else True


class AccessControlTests(APITestCase):
    password = "Cedar!Lantern-47-River"

    def setUp(self):
        cache.clear()
        self.business = Business.objects.create(name="Kigali Works")
        self.employer = self.user("boss", "boss@example.com", role="employer", business=self.business)
        self.other_business = Business.objects.create(name="Other Ltd")
        self.other_employer = self.user("rival", "rival@example.com", role="employer", business=self.other_business)
        self.admin = self.user("platform", "admin@example.com", role="admin")
        self.aline, self.aline_user = self.hire(self.business, "aline@example.com")
        self.bosco, self.bosco_user = self.hire(self.business, "bosco@example.com")
        self.outsider, self.outsider_user = self.hire(self.other_business, "out@example.com")
        self.room = Room.objects.create(business=self.business, name="Room 101", building="Main", floor="1",
                                        door_identifier="door-101")

    def user(self, username, email, **profile):
        user = User.objects.create_user(username, email, self.password)
        AccountProfile.objects.create(user=user, **profile)
        return user

    def hire(self, business, email, approved=True):
        employee = Employee.objects.create(business=business, first_name=email.split("@")[0].title(),
                                           last_name="Test", email=email, job_title="Clerk",
                                           date_joined=date(2026, 1, 1))
        user = self.user(email.split("@")[0], email, role="employee", employee=employee)
        if approved:
            Contract.objects.create(employee=employee, title="Employment", start_date=date(2026, 1, 1),
                                    signature_status="signed", worker_approval_status="approved")
        return employee, user

    def as_user(self, user):
        self.client.force_authenticate(user)

    def unlock(self, room, proof=""):
        return self.client.post(f"/api/access-control/rooms/{room.pk}/unlock/",
                                {"access_method": "nfc", "proximity_proof": proof}, format="json")

    def grant(self, room, email):
        return self.client.post("/api/access-control/grants/", {"room": room.pk, "email": email}, format="json")

    # --- Rooms -------------------------------------------------------------

    def test_only_the_owning_employer_manages_rooms(self):
        self.as_user(self.employer)
        created = self.client.post("/api/access-control/rooms/", {
            "name": "Room 102", "building": "Main", "floor": "1", "door_identifier": "door-102"}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual((created.data["business"], created.data["created_by"], created.data["device_status"]),
                         (self.business.pk, "boss", "not_configured"))
        duplicate = self.client.post("/api/access-control/rooms/", {
            "name": "Room 103", "building": "Main", "floor": "1", "door_identifier": "DOOR-102"}, format="json")
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("door_identifier", duplicate.data)
        renamed = self.client.patch(f"/api/access-control/rooms/{self.room.pk}/", {"name": "Boardroom"}, format="json")
        self.assertEqual(renamed.data["name"], "Boardroom")

        self.as_user(self.other_employer)
        self.assertEqual(self.client.get("/api/access-control/rooms/").data, [])
        for response in (self.client.get(f"/api/access-control/rooms/{self.room.pk}/"),
                         self.client.patch(f"/api/access-control/rooms/{self.room.pk}/", {"name": "x"}, format="json"),
                         self.client.delete(f"/api/access-control/rooms/{self.room.pk}/")):
            self.assertEqual(response.status_code, 404)

        for user in (self.aline_user, self.admin):
            self.as_user(user)
            self.assertEqual(self.client.get("/api/access-control/rooms/").status_code, 403)
            self.assertEqual(self.client.post("/api/access-control/rooms/", {
                "name": "Mine", "building": "Main", "floor": "1", "door_identifier": "x"}, format="json").status_code, 403)
        self.assertTrue(Room.objects.filter(pk=self.room.pk, name="Boardroom").exists())

    # --- Permissions ---------------------------------------------------------

    def test_employer_grants_and_revokes_by_registered_email(self):
        self.as_user(self.employer)
        granted = self.grant(self.room, "ALINE@example.com")
        self.assertEqual(granted.status_code, 201, granted.data)
        self.assertEqual(granted.data["employee"], self.aline.pk)
        self.assertEqual(self.grant(self.room, "aline@example.com").status_code, 400)

        unregistered, _ = self.hire(self.business, "no-account@example.com")
        AccountProfile.objects.filter(employee=unregistered).delete()
        for email in ("out@example.com", "nobody@example.com", "no-account@example.com"):
            self.assertEqual(self.grant(self.room, email).status_code, 400, email)
        other_room = Room.objects.create(business=self.other_business, name="Vault", building="HQ", floor="0",
                                         door_identifier="vault")
        self.assertEqual(self.grant(other_room, "aline@example.com").status_code, 400)

        listed = self.client.get(f"/api/access-control/grants/?room={self.room.pk}").data
        self.assertEqual([row["employee_email"] for row in listed], ["aline@example.com"])
        self.assertEqual(self.client.delete(f"/api/access-control/grants/{granted.data['id']}/").status_code, 204)
        self.assertFalse(RoomAccessGrant.objects.exists())
        changes = self.client.get("/api/access-control/permission-changes/").data
        self.assertEqual([(row["change"], row["employee_email"], row["changed_by"]) for row in changes],
                         [("revoked", "aline@example.com", "boss"), ("granted", "aline@example.com", "boss")])

    def test_employer_grants_many_employees_many_rooms_at_once(self):
        lab = Room.objects.create(business=self.business, name="Lab", building="Main", floor="2", door_identifier="lab")
        RoomAccessGrant.objects.create(room=self.room, employee=self.aline)
        self.as_user(self.employer)
        response = self.client.post("/api/access-control/grants/bulk/", {
            "employees": [self.aline.pk, self.bosco.pk, self.bosco.pk], "rooms": [self.room.pk, lab.pk]}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data["granted"], response.data["already_had_access"]), (3, 1))
        self.assertEqual(RoomAccessGrant.objects.count(), 4)
        self.assertEqual(RoomPermissionChange.objects.filter(change="granted").count(), 3)

        vault = Room.objects.create(business=self.other_business, name="Vault", building="HQ", floor="0",
                                    door_identifier="vault")
        for payload in ({"employees": [self.outsider.pk], "rooms": [self.room.pk]},
                        {"employees": [self.aline.pk], "rooms": [vault.pk]},
                        {"employees": [], "rooms": [self.room.pk]}):
            self.assertEqual(self.client.post("/api/access-control/grants/bulk/", payload, format="json").status_code,
                             400, payload)
        self.as_user(self.aline_user)
        self.assertEqual(self.client.post("/api/access-control/grants/bulk/", {
            "employees": [self.aline.pk], "rooms": [lab.pk]}, format="json").status_code, 403)
        self.assertEqual(RoomAccessGrant.objects.count(), 4)

    def test_employees_and_other_businesses_cannot_change_permissions(self):
        grant = RoomAccessGrant.objects.create(room=self.room, employee=self.bosco)
        self.as_user(self.aline_user)
        self.assertEqual(self.grant(self.room, "aline@example.com").status_code, 403)
        self.assertEqual(self.client.delete(f"/api/access-control/grants/{grant.pk}/").status_code, 403)
        self.as_user(self.other_employer)
        self.assertEqual(self.client.delete(f"/api/access-control/grants/{grant.pk}/").status_code, 404)
        self.assertEqual(self.client.get("/api/access-control/grants/").data, [])
        self.assertEqual(self.grant(self.room, "bosco@example.com").status_code, 400)
        self.assertEqual(RoomAccessGrant.objects.count(), 1)
        self.assertFalse(RoomPermissionChange.objects.exists())

    def test_deleting_a_room_records_its_revoked_permissions_and_keeps_history(self):
        RoomAccessGrant.objects.create(room=self.room, employee=self.aline)
        self.as_user(self.employer)
        self.unlock(self.room)
        self.assertEqual(self.client.delete(f"/api/access-control/rooms/{self.room.pk}/").status_code, 204)
        change = RoomPermissionChange.objects.get()
        self.assertEqual((change.change, change.note, change.room_name), ("revoked", "Room deleted", "Room 101"))
        attempt = RoomAccessAttempt.objects.get()
        self.assertEqual((attempt.room, attempt.room_name), (None, "Room 101"))

    # --- Unlocking -----------------------------------------------------------

    def test_without_door_hardware_nothing_unlocks_and_every_attempt_is_recorded(self):
        RoomAccessGrant.objects.create(room=self.room, employee=self.aline)
        self.as_user(self.aline_user)
        response = self.unlock(self.room, proof="anything")
        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.data["detail"])
        self.as_user(self.employer)
        self.assertEqual(self.unlock(self.room).status_code, 503)
        self.as_user(self.bosco_user)
        self.assertEqual(self.unlock(self.room).status_code, 403)
        self.as_user(self.admin)
        self.assertEqual(self.unlock(self.room).status_code, 403)
        self.as_user(self.outsider_user)
        self.assertEqual(self.unlock(self.room).status_code, 404)
        self.assertEqual(self.client.post("/api/access-control/rooms/999999/unlock/", {"access_method": "nfc"},
                                          format="json").status_code, 404)

        attempts = list(RoomAccessAttempt.objects.order_by("id").values_list(
            "user_email", "result", "denial_reason", "unlock_status"))
        self.assertEqual(attempts, [
            ("aline@example.com", "denied", "hardware_not_configured", ""),
            ("boss@example.com", "denied", "hardware_not_configured", ""),
            ("bosco@example.com", "denied", "no_permission", ""),
            ("admin@example.com", "denied", "admin_no_policy", ""),
            ("out@example.com", "denied", "not_member", ""),
        ])
        self.assertFalse(RoomAccessAttempt.objects.filter(result="granted").exists())

    @override_settings(DOOR_GATEWAY=FAKE_GATEWAY)
    def test_unlock_needs_permission_then_verified_proximity(self):
        RoomAccessGrant.objects.create(room=self.room, employee=self.aline)
        self.as_user(self.aline_user)
        self.assertEqual(self.unlock(self.room).status_code, 403)
        self.assertEqual(self.unlock(self.room, proof="tag-elsewhere").status_code, 403)
        opened = self.unlock(self.room, proof="tag-door-101")
        self.assertEqual(opened.status_code, 200, opened.data)
        self.assertEqual((opened.data["result"], opened.data["unlock_status"]), ("granted", "confirmed"))

        self.as_user(self.bosco_user)
        self.assertEqual(self.unlock(self.room, proof="tag-door-101").status_code, 403)
        self.as_user(self.admin)
        self.assertEqual(self.unlock(self.room, proof="tag-door-101").status_code, 403)
        self.as_user(self.employer)
        silent = Room.objects.create(business=self.business, name="Store", building="Main", floor="0",
                                     door_identifier="silent")
        broken = Room.objects.create(business=self.business, name="Lab", building="Main", floor="2",
                                     door_identifier="broken")
        self.assertEqual(self.unlock(silent, proof="tag-silent").data["unlock_status"], "unconfirmed")
        self.assertEqual(self.unlock(broken, proof="tag-broken").status_code, 502)

        self.assertEqual(list(RoomAccessAttempt.objects.order_by("id").values_list(
            "user_email", "result", "denial_reason", "unlock_status")), [
            ("aline@example.com", "denied", "proximity_failed", ""),
            ("aline@example.com", "denied", "proximity_failed", ""),
            ("aline@example.com", "granted", "", "confirmed"),
            ("bosco@example.com", "denied", "no_permission", ""),
            ("admin@example.com", "denied", "admin_no_policy", ""),
            ("boss@example.com", "granted", "", "unconfirmed"),
            ("boss@example.com", "granted", "", "failed"),
        ])

    @override_settings(DOOR_GATEWAY=FAKE_GATEWAY)
    def test_revoked_inactive_and_unapproved_employees_cannot_unlock(self):
        grant = RoomAccessGrant.objects.create(room=self.room, employee=self.aline)
        self.as_user(self.aline_user)
        self.assertEqual(self.unlock(self.room, proof="tag-door-101").status_code, 200)
        grant.delete()
        self.assertEqual(self.unlock(self.room, proof="tag-door-101").status_code, 403)

        RoomAccessGrant.objects.create(room=self.room, employee=self.aline)
        Employee.objects.filter(pk=self.aline.pk).update(is_active=False)
        self.as_user(User.objects.get(pk=self.aline_user.pk))
        self.assertEqual(self.unlock(self.room, proof="tag-door-101").status_code, 403)

        newcomer, newcomer_user = self.hire(self.business, "new@example.com", approved=False)
        RoomAccessGrant.objects.create(room=self.room, employee=newcomer)
        self.as_user(newcomer_user)
        self.assertEqual(self.unlock(self.room, proof="tag-door-101").status_code, 403)
        self.assertEqual(list(RoomAccessAttempt.objects.filter(result="denied").order_by("id")
                              .values_list("denial_reason", flat=True)),
                         ["no_permission", "inactive", "not_approved"])

    def test_unlock_request_must_name_a_supported_method(self):
        self.as_user(self.employer)
        response = self.client.post(f"/api/access-control/rooms/{self.room.pk}/unlock/", {"access_method": "wifi"},
                                    format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(RoomAccessAttempt.objects.exists())

    # --- What each role sees ---------------------------------------------------

    def test_history_and_rooms_are_scoped_to_each_role(self):
        RoomAccessGrant.objects.create(room=self.room, employee=self.aline)
        Room.objects.create(business=self.business, name="Room 102", building="Main", floor="1",
                            door_identifier="door-102")
        vault = Room.objects.create(business=self.other_business, name="Vault", building="HQ", floor="0",
                                    door_identifier="vault")
        for user, room in ((self.aline_user, self.room), (self.bosco_user, self.room),
                           (self.other_employer, vault)):
            self.as_user(user)
            self.unlock(room)

        self.as_user(self.employer)
        history = self.client.get("/api/access-control/history/").data
        self.assertEqual(sorted(row["user_email"] for row in history), ["aline@example.com", "bosco@example.com"])
        self.assertEqual(len(self.client.get("/api/access-control/history/?result=granted").data), 0)

        self.as_user(self.aline_user)
        mine = self.client.get("/api/me/access-history/").data
        self.assertEqual([row["user_email"] for row in mine], ["aline@example.com"])
        rooms = self.client.get("/api/me/rooms/").data
        self.assertEqual([(row["name"], row["can_unlock"]) for row in rooms], [("Room 101", True), ("Room 102", False)])
        self.assertNotIn("door_identifier", rooms[0])

        self.as_user(self.employer)
        self.assertEqual(self.client.get("/api/me/rooms/").status_code, 403)
        _, unapproved = self.hire(self.business, "new@example.com", approved=False)
        self.as_user(unapproved)
        self.assertEqual(self.client.get("/api/me/rooms/").status_code, 403)

    def test_admin_oversees_every_business_read_only(self):
        RoomAccessGrant.objects.create(room=self.room, employee=self.aline)
        Room.objects.create(business=self.other_business, name="Vault", building="HQ", floor="0",
                            door_identifier="vault")
        self.as_user(self.aline_user)
        self.unlock(self.room)
        self.as_user(self.admin)
        rooms = self.client.get("/api/admin/records/rooms/").data
        self.assertEqual(sorted(row["name"] for row in rooms), ["Room 101", "Vault"])
        self.assertEqual(len(self.client.get(f"/api/admin/records/rooms/?business={self.other_business.pk}").data), 1)
        grants = self.client.get(f"/api/admin/records/room-access-grants/?business={self.business.pk}").data
        self.assertEqual([row["employee_email"] for row in grants], ["aline@example.com"])
        history = self.client.get(f"/api/admin/records/room-access-history/?employee={self.aline.pk}").data
        self.assertEqual([row["user_email"] for row in history], ["aline@example.com"])
        self.assertEqual(self.client.get(f"/api/admin/records/room-access-history/?employee={self.bosco.pk}").data, [])
        self.assertEqual(self.client.post("/api/access-control/rooms/", {}, format="json").status_code, 403)

    # --- Door Simulator ------------------------------------------------------------

    def test_door_simulator_unlocks_for_granted_employees_then_relocks(self):
        RoomAccessGrant.objects.create(room=self.room, employee=self.aline)
        simulator = f"/api/access-control/simulator/{self.room.pk}/"
        self.as_user(self.employer)
        started = self.client.post(simulator)
        self.assertEqual(started.status_code, 200, started.data)
        self.assertTrue(started.data["locked"])
        self.assertRegex(started.data["door_code"], r"^\d{4}$")
        self.assertTrue(0 < started.data["code_changes_in"] <= 30)
        code = started.data["door_code"]

        def enter(proof, method="door_code"):
            return self.client.post(f"/api/access-control/rooms/{self.room.pk}/unlock/",
                                    {"access_method": method, "proximity_proof": proof}, format="json")

        self.as_user(self.aline_user)
        self.assertEqual(self.client.get("/api/me/rooms/").data[0]["device_status"], "simulator")
        self.assertNotIn("door_code", str(self.client.get("/api/me/rooms/").data))
        wrong = enter("0000" if code != "0000" else "1111")
        self.assertEqual((wrong.status_code, wrong.data["detail"]),
                         (403, "That door code is not right. Check the code on the door screen and try again."))
        self.assertEqual(enter("").status_code, 403)
        self.assertEqual(enter(code, method="range").status_code, 400)
        opened = enter(f" {code} ")
        self.assertEqual((opened.status_code, opened.data["unlock_status"]), (200, "confirmed"))

        self.as_user(self.bosco_user)
        self.assertEqual(enter(code).status_code, 403)

        self.as_user(self.employer)
        door = self.client.get(simulator).data
        self.assertFalse(door["locked"])
        self.assertGreater(door["relocks_in"], 0)
        self.assertEqual([(row["result"], row["denial_reason"]) for row in door["recent"]],
                         [("denied", "no_permission"), ("granted", ""), ("denied", "proximity_failed"),
                          ("denied", "proximity_failed")])
        SimulatedDoor.objects.filter(room=self.room).update(unlocked_until=timezone.now() - timedelta(seconds=1))
        self.assertTrue(self.client.get(simulator).data["locked"])
        self.assertEqual(self.client.get("/api/access-control/history/?result=granted").data[0]["access_method"],
                         "door_code")

        self.assertEqual(self.client.delete(simulator).status_code, 204)
        self.as_user(self.aline_user)
        self.assertEqual(enter(code).status_code, 503)

    def test_only_the_owning_employer_runs_the_simulator_and_it_stops_when_abandoned(self):
        simulator = f"/api/access-control/simulator/{self.room.pk}/"
        for user in (self.aline_user, self.admin):
            self.as_user(user)
            self.assertEqual(self.client.post(simulator).status_code, 403)
        self.as_user(self.other_employer)
        self.assertEqual(self.client.post(simulator).status_code, 404)
        self.assertFalse(SimulatedDoor.objects.exists())

        self.as_user(self.employer)
        code = self.client.post(simulator).data["door_code"]
        SimulatedDoor.objects.update(last_seen_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.get("/api/access-control/rooms/").data[0]["device_status"], "not_configured")
        self.assertEqual(self.client.post(f"/api/access-control/rooms/{self.room.pk}/unlock/",
                                          {"access_method": "door_code", "proximity_proof": code},
                                          format="json").status_code, 503)

    def test_removing_employees_and_businesses_still_works(self):
        RoomAccessGrant.objects.create(room=self.room, employee=self.aline)
        self.as_user(self.aline_user)
        self.unlock(self.room)
        purge_employee(self.aline)
        attempt = RoomAccessAttempt.objects.get()
        self.assertEqual((attempt.employee, attempt.user, attempt.user_email), (None, None, "aline@example.com"))
        self.assertFalse(RoomAccessGrant.objects.exists())
        purge_business(self.business)
        self.assertFalse(Room.objects.exists())
        self.assertFalse(RoomAccessAttempt.objects.exists())
