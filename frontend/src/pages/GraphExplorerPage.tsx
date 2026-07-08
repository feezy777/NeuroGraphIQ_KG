import { useState } from 'react'

type GraphTab = 'focus' | 'global' | 'browser'

export function GraphExplorerPage() {
  const [tab, setTab] = useState<GraphTab>('global')

  return (
    <div style={{ padding: 24, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0 }}>🧠 图谱探索</h2>
          <p style={{ color: '#888', fontSize: 13, margin: '4px 0 0' }}>
            脑知识图谱可视化 — 聚焦探索 · 全局力导向图 · Neo4j Browser
          </p>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          <button className={`btn${tab === 'focus' ? ' btn-primary' : ''}`} onClick={() => setTab('focus')}>
            🔍 聚焦探索
          </button>
          <button className={`btn${tab === 'global' ? ' btn-primary' : ''}`} onClick={() => setTab('global')}>
            🌐 全局图谱
          </button>
          <button className={`btn${tab === 'browser' ? ' btn-primary' : ''}`} onClick={() => setTab('browser')}>
            💻 Neo4j Browser
          </button>
        </div>
      </div>

      <div style={{ flex: 1, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        {tab === 'browser' ? (
          <iframe
            src="http://localhost:7474/browser"
            style={{ width: '100%', height: '100%', border: 'none' }}
            title="Neo4j Browser"
          />
        ) : tab === 'focus' ? (
          <FocusView />
        ) : (
          <GlobalView />
        )}
      </div>
    </div>
  )
}

function FocusView() {
  return (
    <div style={{ display: 'flex', height: '100%' }}>
      <div style={{ width: 280, borderRight: '1px solid var(--border)', padding: 16, overflow: 'auto' }}>
        <input className="form-input" placeholder="搜索脑区名称…" style={{ marginBottom: 12 }} />
        <div style={{ fontSize: 12, color: '#888' }}>
          <p>选择一个脑区开始探索。点击节点展开邻居，拖动节点调整布局。</p>
          <p style={{ marginTop: 8 }}>深度：</p>
          <input type="range" min={1} max={3} defaultValue={1} style={{ width: '100%' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
            <span>1</span><span>2</span><span>3</span>
          </div>
        </div>
      </div>
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#888' }}>
        <div style={{ textAlign: 'center' }}>
          <p style={{ fontSize: 48, margin: 0 }}>🔍</p>
          <p>聚焦探索模式 — 选择脑区开始</p>
          <p style={{ fontSize: 12 }}>需要 Neo4j + 数据同步完成后启用</p>
        </div>
      </div>
    </div>
  )
}

function GlobalView() {
  return (
    <div style={{ display: 'flex', height: '100%' }}>
      <div style={{ width: 280, borderRight: '1px solid var(--border)', padding: 16, overflow: 'auto' }}>
        <h4 style={{ margin: '0 0 12px', fontSize: 13 }}>筛选</h4>
        <label style={{ display: 'block', fontSize: 12, marginBottom: 8 }}>
          连接类型
          <select className="form-input" style={{ marginTop: 4 }}>
            <option>全部</option>
            <option>structural_connection</option>
            <option>functional_connectivity</option>
            <option>projection</option>
          </select>
        </label>
        <label style={{ display: 'block', fontSize: 12, marginBottom: 8 }}>
          最小置信度
          <input type="range" min={0} max={100} defaultValue={30} style={{ width: '100%' }} />
        </label>
        <label style={{ display: 'block', fontSize: 12, marginBottom: 8 }}>
          高亮回路
          <select className="form-input" style={{ marginTop: 4 }}>
            <option>无</option>
          </select>
        </label>
        <div className="data-center-field-completion-boundary" style={{ marginTop: 12, fontSize: 11 }}>
          <p>96 脑区 · 力导向布局</p>
          <p>需要 Neo4j + 数据同步完成后启用</p>
        </div>
      </div>
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#888' }}>
        <div style={{ textAlign: 'center' }}>
          <p style={{ fontSize: 48, margin: 0 }}>🌐</p>
          <p>全局力导向图 — 96 脑区全量渲染</p>
          <p style={{ fontSize: 12 }}>需要 Docker Neo4j 启动 + 数据同步完成后启用</p>
        </div>
      </div>
    </div>
  )
}
