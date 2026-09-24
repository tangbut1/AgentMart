import { NavLink, Outlet, Link } from "react-router-dom";
import { Icon } from "./ui";

const NAV = [
  { to: "/", label: "比价首页", end: true },
  { to: "/browser", label: "发起比价", end: true },
  { to: "/browser/settings", label: "平台与模型", end: false },
];

export default function Layout() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        跳到主要内容
      </a>
      <header className="site-header">
        <div className="container site-header__inner">
          <Link to="/" className="brand">
            <span className="brand__mark" aria-hidden="true">
              参
            </span>
            <span>
              <span className="brand__name">购物参谋</span>
              <span className="brand__sub">AgentMart</span>
            </span>
          </Link>
          <nav className="nav" aria-label="主导航">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `nav__link${isActive ? " nav__link--active" : ""}`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <main id="main" className="main">
        <div className="container">
          <Outlet />
        </div>
      </main>

      <footer className="site-footer">
        <div className="container site-footer__inner">
          <span>
            购物参谋 · 跨平台智能购物决策 —— 所有价格、优惠与政策均标注来源与核验状态，
            演示数据与真实数据严格分离。
          </span>
          <span className="row gap-6">
            <Icon name="shield" size={14} />
            <span>不代领券 · 不代下单 · 不代付款 · 不收集账号密码</span>
          </span>
        </div>
      </footer>
    </div>
  );
}
