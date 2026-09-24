import { useEffect, useRef, useState } from "react";
import type { CommercialRelation, Review } from "../lib/api";
import { api } from "../lib/api";
import { COMMERCIAL_RELATION_LABEL } from "../lib/format";
import ReviewCard from "../components/ReviewCard";
import { EmptyState, Icon, Notice } from "../components/ui";

const LIST_FIELDS: { key: "pros" | "cons" | "quotes" | "test_evidence" | "scenarios"; label: string; hint: string }[] = [
  { key: "pros", label: "优点", hint: "每行一条，整理自评测内容" },
  { key: "cons", label: "不足与注意事项", hint: "每行一条" },
  { key: "quotes", label: "原文摘录", hint: "每行一句原话，系统不改写" },
  { key: "test_evidence", label: "测试方法与可复核数据", hint: "例如：连续佩戴 3 小时 / 实测降噪 32dB" },
  { key: "scenarios", label: "适用场景 / 人群", hint: "例如：通勤族 / 学生党" },
];

function toLines(text: string): string[] {
  return text
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function ReviewsPage() {
  const [reviews, setReviews] = useState<Review[] | null>(null);
  const [includeDemo, setIncludeDemo] = useState(false);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [url, setUrl] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolveNotice, setResolveNotice] = useState<string | null>(null);
  const [form, setForm] = useState({
    title: "",
    creator_name: "",
    model_tested: "",
    pros: "",
    cons: "",
    quotes: "",
    test_evidence: "",
    scenarios: "",
    commercial_relation: "unknown" as CommercialRelation,
    curator_notes: "",
    related_models: "",
    submitter: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitResult, setSubmitResult] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const load = async (demo: boolean) => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const list = await api.reviews({ includeDemo: demo }, ac.signal);
      setReviews(list);
      setError(null);
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
    }
  };

  useEffect(() => {
    load(includeDemo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [includeDemo]);

  const onResolve = async () => {
    if (!url.trim()) return;
    setResolving(true);
    setResolveNotice(null);
    try {
      const res = await api.resolveReview(url.trim());
      if (res.ok && res.review) {
        setForm((f) => ({
          ...f,
          title: res.review!.title || f.title,
          creator_name: res.review!.creator_name || f.creator_name,
          model_tested: f.model_tested,
        }));
        setSubmitResult(null);
      } else {
        setResolveNotice(res.error ?? "解析失败");
      }
    } catch (e) {
      setResolveNotice((e as Error).message);
    } finally {
      setResolving(false);
    }
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    setSubmitting(true);
    setSubmitResult(null);
    try {
      await api.submitReview({
        url: url.trim(),
        title: form.title || null,
        creator_name: form.creator_name || null,
        model_tested: form.model_tested || null,
        pros: toLines(form.pros),
        cons: toLines(form.cons),
        quotes: toLines(form.quotes),
        test_evidence: toLines(form.test_evidence),
        scenarios: toLines(form.scenarios),
        commercial_relation: form.commercial_relation,
        curator_notes: form.curator_notes || null,
        related_models: toLines(form.related_models),
        submitter: form.submitter || "anonymous",
      });
      setSubmitResult(
        "已提交。提交内容进入「待整理」状态，经核实后才会出现在商品详情的评测区并影响参考价值评分。",
      );
      setUrl("");
      setForm((f) => ({ ...f, pros: "", cons: "", quotes: "", test_evidence: "", scenarios: "" }));
      load(includeDemo);
    } catch (err) {
      setSubmitResult(`提交失败：${(err as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const filtered = (reviews ?? []).filter((r) => {
    if (!filter.trim()) return true;
    const q = filter.trim().toLowerCase();
    return (
      r.title.toLowerCase().includes(q) ||
      (r.model_tested ?? "").toLowerCase().includes(q) ||
      r.related_models.some((m) => m.toLowerCase().includes(q)) ||
      r.creator_name.toLowerCase().includes(q)
    );
  });

  return (
    <div className="stack gap-24">
      <div className="detail-head">
        <h1 className="detail-title">专业评测</h1>
        <p className="page-lede">
          评测不按粉丝量排序，而按五个可复核维度评估：是否实测该型号、是否给出测试方法与数据、
          是否说明使用条件与局限、是否披露商业合作关系、观点是否有足够内容支撑。
          原文摘录与整理内容分开呈现，AI 归纳会单独标注。
        </p>
      </div>

      <section className="panel">
        <div className="panel__head">
          <span style={{ color: "var(--primary)" }}>
            <Icon name="review" size={18} />
          </span>
          <h2 className="section-title">
            提交评测链接并整理
            <span className="section-note">系统只解析公开元数据，观点与结论由整理人填写</span>
          </h2>
        </div>
        <form onSubmit={onSubmit}>
          <div className="panel__body stack gap-16">
            <div className="grid-2">
              <div className="field">
                <label className="field__label" htmlFor="review-url">
                  评测链接
                </label>
                <div className="row gap-8">
                  <input
                    id="review-url"
                    className="input"
                    type="url"
                    required
                    placeholder="https://www.bilibili.com/video/BV..."
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn btn--secondary"
                    onClick={onResolve}
                    disabled={resolving || !url.trim()}
                  >
                    {resolving ? "解析中…" : "解析元数据"}
                  </button>
                </div>
                <span className="field__hint">
                  哔哩哔哩链接可自动解析真实元数据（标题、UP 主、发布时间、播放量）；
                  其他平台请手动填写。系统不会抓取需要登录的内容。
                </span>
              </div>

              <div className="stack gap-12">
                <div className="field">
                  <label className="field__label" htmlFor="review-model">
                    测试型号
                  </label>
                  <input
                    id="review-model"
                    className="input"
                    placeholder="例如：索尼 WH-1000XM5 黑色"
                    value={form.model_tested}
                    onChange={(e) => setForm({ ...form, model_tested: e.target.value })}
                  />
                </div>
                <div className="field">
                  <label className="field__label" htmlFor="review-related">
                    关联型号（每行一个）
                  </label>
                  <textarea
                    id="review-related"
                    className="textarea"
                    style={{ minHeight: 40 }}
                    value={form.related_models}
                    onChange={(e) => setForm({ ...form, related_models: e.target.value })}
                  />
                </div>
              </div>
            </div>

            {resolveNotice && (
              <Notice tone="warn" title="解析提示">
                {resolveNotice}
              </Notice>
            )}

            <div className="grid-2">
              <div className="field">
                <label className="field__label" htmlFor="review-title">
                  标题
                </label>
                <input
                  id="review-title"
                  className="input"
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                />
              </div>
              <div className="field">
                <label className="field__label" htmlFor="review-creator">
                  创作者 / UP 主
                </label>
                <input
                  id="review-creator"
                  className="input"
                  value={form.creator_name}
                  onChange={(e) => setForm({ ...form, creator_name: e.target.value })}
                />
              </div>
            </div>

            <div className="grid-2">
              {LIST_FIELDS.map((f) => (
                <div className="field" key={f.key}>
                  <label className="field__label" htmlFor={`review-${f.key}`}>
                    {f.label}
                  </label>
                  <textarea
                    id={`review-${f.key}`}
                    className="textarea"
                    placeholder={f.hint}
                    value={form[f.key]}
                    onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  />
                </div>
              ))}
            </div>

            <div className="grid-2">
              <div className="field">
                <label className="field__label" htmlFor="review-commercial">
                  商业合作关系
                </label>
                <select
                  id="review-commercial"
                  className="select"
                  value={form.commercial_relation}
                  onChange={(e) =>
                    setForm({ ...form, commercial_relation: e.target.value as CommercialRelation })
                  }
                >
                  {(Object.keys(COMMERCIAL_RELATION_LABEL) as CommercialRelation[]).map((k) => (
                    <option value={k} key={k}>
                      {COMMERCIAL_RELATION_LABEL[k]}
                    </option>
                  ))}
                </select>
                <span className="field__hint">
                  未知合作关系会降低该评测的参考价值评分
                </span>
              </div>
              <div className="field">
                <label className="field__label" htmlFor="review-submitter">
                  整理人署名
                </label>
                <input
                  id="review-submitter"
                  className="input"
                  placeholder="anonymous"
                  value={form.submitter}
                  onChange={(e) => setForm({ ...form, submitter: e.target.value })}
                />
              </div>
            </div>

            <div className="field">
              <label className="field__label" htmlFor="review-notes">
                整理备注（可选）
              </label>
              <input
                id="review-notes"
                className="input"
                value={form.curator_notes}
                onChange={(e) => setForm({ ...form, curator_notes: e.target.value })}
              />
            </div>

            {submitResult && (
              <Notice tone={submitResult.startsWith("提交失败") ? "danger" : "info"} title="提交结果">
                {submitResult}
              </Notice>
            )}

            <div className="row gap-12 wrap">
              <button className="btn btn--primary" type="submit" disabled={submitting || !url.trim()}>
                {submitting ? "提交中…" : "提交整理内容"}
              </button>
              <span className="small muted">
                提交即表示确认内容来自公开评测的如实整理，未虚构创作者观点。
              </span>
            </div>
          </div>
        </form>
      </section>

      <section className="stack gap-12">
        <div className="panel__head panel__head--plain" style={{ padding: "0 0 8px" }}>
          <h2 className="section-title">
            已提交的评测
            <span className="section-note">
              {reviews ? `${reviews.length} 条` : "加载中"}
            </span>
          </h2>
          <div className="panel__actions">
            <input
              className="input"
              style={{ width: 220 }}
              placeholder="按标题 / 型号 / 创作者筛选"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <label className="checkbox">
              <input
                type="checkbox"
                checked={includeDemo}
                onChange={(e) => setIncludeDemo(e.target.checked)}
              />
              含演示数据
            </label>
          </div>
        </div>

        {error && <Notice tone="danger" title="加载失败">{error}</Notice>}

        {reviews === null && !error && (
          <div className="panel">
            <div className="panel__body">
              <span className="skeleton" style={{ display: "block", height: 90 }} />
            </div>
          </div>
        )}

        {reviews !== null && filtered.length === 0 && (
          <div className="panel">
            <EmptyState
              icon={<Icon name="review" size={20} />}
              title="暂无评测"
              desc="还没有提交过评测链接。粘贴一个 B 站或抖音的公开评测链接，填写整理内容后即可入库。"
            />
          </div>
        )}

        <div className="stack gap-12">
          {filtered.map((r) => (
            <ReviewCard key={r.id} review={r} />
          ))}
        </div>
      </section>
    </div>
  );
}
