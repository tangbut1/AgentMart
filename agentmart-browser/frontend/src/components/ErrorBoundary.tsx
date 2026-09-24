import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * 渲染崩溃时的兜底。
 *
 * 没有它的话，组件里一个未定义字段就能让整页变白，用户既看不到错误
 * 也不知道该做什么。这里至少把原因摆出来，并给一条能自己恢复的出路。
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 只在控制台留一份，不往任何地方上报
    console.error("页面渲染出错：", error, info.componentStack);
  }

  private reset = () => {
    this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="stack gap-16" style={{ maxWidth: 720, margin: "48px auto" }}>
        <div className="panel">
          <div className="panel__head">
            <span style={{ color: "var(--danger, #c0392b)" }}>⚠</span>
            <h2 className="section-title">这个页面没能显示出来</h2>
          </div>
          <div className="panel__body stack gap-12">
            <p>
              界面在渲染时出错了，不是你的操作有问题。可以把下面的信息发给维护者，
              或者直接刷新页面重试。
            </p>
            <pre
              className="small"
              style={{
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                background: "var(--surface-2, #f5f5f5)",
                padding: 12,
                borderRadius: 8,
                margin: 0,
              }}
            >
              {error.message || String(error)}
            </pre>
            <div className="row gap-8 wrap">
              <button
                type="button"
                className="btn btn--primary btn--sm"
                onClick={() => window.location.reload()}
              >
                刷新页面
              </button>
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={this.reset}
              >
                试着继续
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }
}
