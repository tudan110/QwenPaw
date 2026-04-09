import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import DigitalEmployeeAvatar from "../../components/DigitalEmployeeAvatar";
import {
  digitalEmployees,
  opsExpertCategories,
  opsExperts,
} from "../../data/portalData";
import { buildEmployeePagePath } from "./helpers";
import "../ops-expert.css";

export function OpsExpertPanel() {
  const [searchText, setSearchText] = useState("");
  const [activeMainTab, setActiveMainTab] = useState<"community" | "mine">("community");
  const [activeCategory, setActiveCategory] = useState("all");
  const [addedExperts, setAddedExperts] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState("");
  const toastTimerRef = useRef<number | null>(null);

  const showToast = (message: string) => {
    setToast(message);
    if (toastTimerRef.current) {
      window.clearTimeout(toastTimerRef.current);
    }
    toastTimerRef.current = window.setTimeout(() => setToast(""), 1800);
  };

  const handleAddExpert = (expertId: string, expertName: string) => {
    if (addedExperts.has(expertId)) return;
    setAddedExperts((prev) => new Set(prev).add(expertId));
    showToast(`${expertName} 已加入数字员工统一入口！`);
  };

  const filteredExperts = useMemo(() => {
    return opsExperts.filter((expert) => {
      const matchCategory =
        activeCategory === "all" || expert.category === activeCategory;
      const matchSearch =
        !searchText ||
        expert.name.toLowerCase().includes(searchText.toLowerCase()) ||
        expert.title.toLowerCase().includes(searchText.toLowerCase()) ||
        expert.tags.some((t) =>
          t.toLowerCase().includes(searchText.toLowerCase()),
        );
      return matchCategory && matchSearch;
    });
  }, [activeCategory, searchText]);

  const myExperts = useMemo(() => {
    return opsExperts.filter((expert) => addedExperts.has(expert.id));
  }, [addedExperts]);

  return (
    <div className="ops-expert-panel">
      {toast ? <div className="toast-message">{toast}</div> : null}

      <div className="ops-expert-header">
        <div className="ops-expert-title">
          运维专家 <small>数字员工专家库</small>
        </div>
      </div>

      <div className="ops-expert-search">
        <input
          className="ops-expert-search-input"
          placeholder="搜索运维专家..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
        />
        <button className="ops-expert-search-btn" onClick={() => {}}>
          搜索
        </button>
      </div>

      <div className="ops-expert-tabs">
        <button
          className={
            activeMainTab === "community"
              ? "ops-expert-tab active"
              : "ops-expert-tab"
          }
          onClick={() => setActiveMainTab("community")}
        >
          专家社区
        </button>
        <button
          className={
            activeMainTab === "mine"
              ? "ops-expert-tab active"
              : "ops-expert-tab"
          }
          onClick={() => setActiveMainTab("mine")}
        >
          我的专家{myExperts.length > 0 ? ` (${myExperts.length})` : ""}
        </button>
      </div>

      {activeMainTab === "community" ? (
        <>
          <div className="ops-expert-category-tabs">
            {opsExpertCategories.map((cat) => (
              <button
                key={cat.id}
                className={
                  cat.id === activeCategory
                    ? "ops-expert-category-tab active"
                    : "ops-expert-category-tab"
                }
                onClick={() => setActiveCategory(cat.id)}
              >
                {cat.label}
              </button>
            ))}
          </div>

          <div className="ops-expert-grid">
            {digitalEmployees.map((emp) => (
              <Link
                key={emp.id}
                to={buildEmployeePagePath(emp)}
                className="ops-expert-card is-employee"
                style={{
                  borderColor: `${emp.gradient.match(/#[0-9a-fA-F]{6}/)?.[0] ?? "#3b82f6"}33`,
                  textDecoration: "none",
                }}
              >
                <DigitalEmployeeAvatar
                  employee={emp}
                  className="ops-expert-avatar"
                  style={
                    {
                      "--de-avatar-size": "64px",
                      "--de-avatar-radius": "50%",
                      "--de-avatar-icon-size": "28px",
                      "--de-avatar-animation-size": "32px",
                    } as React.CSSProperties
                  }
                />
                <h4>{emp.name}</h4>
                <p>{emp.desc}</p>
                <div className="ops-expert-tags">
                  <span
                    className="ops-expert-employee-badge"
                    style={{
                      background: `${emp.gradient.match(/#[0-9a-fA-F]{6}/)?.[0] ?? "#3b82f6"}18`,
                      color:
                        emp.gradient.match(/#[0-9a-fA-F]{6}/)?.[0] ??
                        "#3b82f6",
                    }}
                  >
                    数字员工
                  </span>
                </div>
                <span className="ops-expert-built-in-btn">
                  ✓ 已在统一入口中
                </span>
              </Link>
            ))}

            {filteredExperts.map((expert) => (
              <div
                key={expert.id}
                className="ops-expert-card"
                style={{ borderColor: `${expert.color}33` }}
              >
                <div
                  className="ops-expert-avatar"
                  style={{ background: expert.bg }}
                >
                  {expert.avatar}
                </div>
                <h4>{expert.name}</h4>
                <p>{expert.title}</p>
                <div className="ops-expert-tags">
                  {expert.tags.map((tag) => (
                    <span key={tag} className="ops-expert-tag">
                      {tag}
                    </span>
                  ))}
                </div>
                <button
                  className={
                    addedExperts.has(expert.id)
                      ? "ops-expert-add-btn added"
                      : "ops-expert-add-btn"
                  }
                  onClick={() => handleAddExpert(expert.id, expert.name)}
                >
                  {addedExperts.has(expert.id)
                    ? "✓ 已添加"
                    : "+ 加入数字员工统一入口"}
                </button>
              </div>
            ))}

            {filteredExperts.length === 0 && digitalEmployees.length === 0 ? (
              <div className="ops-expert-empty">
                <i className="fa-solid fa-search" />
                <p>没有找到匹配的专家</p>
              </div>
            ) : null}
          </div>
        </>
      ) : (
        <div className="ops-expert-grid">
          {myExperts.length > 0 ? (
            myExperts.map((expert) => (
              <div
                key={expert.id}
                className="ops-expert-card"
                style={{ borderColor: `${expert.color}33` }}
              >
                <div
                  className="ops-expert-avatar"
                  style={{ background: expert.bg }}
                >
                  {expert.avatar}
                </div>
                <h4>{expert.name}</h4>
                <p>{expert.title}</p>
                <div className="ops-expert-tags">
                  {expert.tags.map((tag) => (
                    <span key={tag} className="ops-expert-tag">
                      {tag}
                    </span>
                  ))}
                </div>
                <span className="ops-expert-add-btn added">✓ 已添加</span>
              </div>
            ))
          ) : (
            <div className="ops-expert-empty">
              <i className="fa-solid fa-user-plus" />
              <p>还没有添加专家，去专家社区看看吧</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
