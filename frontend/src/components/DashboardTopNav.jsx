import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router";

// Top bar shared by the employer, super admin and employee dashboards. An item is
// either a link ({ label, to, end, badge, badgeLabel, selected }) or a dropdown
// ({ label, items }). `selected` overrides URL matching for pages that work out
// the current view themselves.
export default function DashboardTopNav({ items, identity, navLabel, onLogout }) {
  const { pathname } = useLocation();
  const [openMenu, setOpenMenu] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);
  const header = useRef(null);
  const name = identity.name || "Account";

  useEffect(() => {
    if (!openMenu && !mobileOpen) return;
    const closeOutside = (event) => {
      if (header.current?.contains(event.target)) return;
      setOpenMenu("");
      setMobileOpen(false);
    };
    const closeOnEscape = (event) => {
      if (event.key !== "Escape") return;
      if (openMenu) {
        header.current?.querySelector(`[data-menu="${openMenu}"]`)?.focus();
        setOpenMenu("");
      } else setMobileOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [openMenu, mobileOpen]);

  const close = () => { setOpenMenu(""); setMobileOpen(false); };
  const toggle = (menu) => setOpenMenu((current) => current === menu ? "" : menu);
  const isCurrent = (to) => pathname === to || pathname.startsWith(`${to}/`);
  const link = (entry, className) => <NavLink key={entry.to} end={entry.end} to={entry.to} onClick={close} className={({ isActive }) => `${className}${(entry.selected ?? isActive) ? " selected" : ""}`}>
    <span>{entry.label}</span>
    {entry.badge > 0 && <span className="attention-badge" aria-label={entry.badgeLabel}>{entry.badge}</span>}
  </NavLink>;

  return <header className="topnav" ref={header}>
    <div className="topnav-row">
      <span className="brand topnav-brand"><span className="brand-mark" aria-hidden="true">E</span><span>Employee<span className="brand-dot">.</span></span></span>
      <div className="topnav-actions">
        <button type="button" className="topnav-toggle" aria-expanded={mobileOpen} aria-controls="dashboard-nav" onClick={() => { setOpenMenu(""); setMobileOpen((open) => !open); }}>{mobileOpen ? "Close" : "Menu"}</button>
        <div className="topnav-menu">
          <button type="button" className="topnav-account-button" data-menu="account" aria-expanded={openMenu === "account"} aria-controls="dashboard-account-menu" onClick={() => toggle("account")}>
            <span className="topnav-account-avatar" aria-hidden="true">{name[0].toUpperCase()}</span>
            <span className="topnav-account-name">{name}</span>
            <span className="topnav-caret" aria-hidden="true">▾</span>
          </button>
          {openMenu === "account" && <div id="dashboard-account-menu" className="topnav-dropdown topnav-dropdown-end">
            <div className="topnav-account-card">
              <small>{identity.eyebrow}</small>
              <strong>{name}</strong>
              <span>{identity.role}</span>
              {identity.detail && <span>{identity.detail}</span>}
            </div>
          </div>}
        </div>
        <button type="button" className="topnav-signout" onClick={onLogout}>Sign out</button>
      </div>
    </div>
    <nav id="dashboard-nav" className={`topnav-tabs${mobileOpen ? " open" : ""}`} aria-label={navLabel}>
      {items.map((item) => {
        if (!item.items) return link(item, "topnav-tab");
        const total = item.items.reduce((sum, entry) => sum + (entry.badge || 0), 0);
        const menuId = `dashboard-menu-${item.label.toLowerCase()}`;
        return <div className="topnav-menu" key={item.label}>
          <button type="button" data-menu={item.label} aria-expanded={openMenu === item.label} aria-controls={menuId}
            className={`topnav-tab topnav-tab-group${item.items.some((entry) => isCurrent(entry.to)) ? " selected" : ""}`} onClick={() => toggle(item.label)}>
            <span>{item.label}</span>
            {total > 0 && <span className="attention-badge" aria-label={`${total} updates in ${item.label}`}>{total}</span>}
            <span className="topnav-caret" aria-hidden="true">▾</span>
          </button>
          {openMenu === item.label && <div id={menuId} className="topnav-dropdown">{item.items.map((entry) => link(entry, "topnav-dropdown-link"))}</div>}
        </div>;
      })}
    </nav>
  </header>;
}
