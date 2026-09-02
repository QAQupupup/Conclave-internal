/**
 * 报告块渲染器测试（report-block-renderer.tsx）
 *
 * 覆盖场景：
 * 1. parseApiEndpoint 纯函数：完整格式 / 无方法 / 无描述 / 单段文本（边界）
 * 2. formatTrace 纯函数：字符串 / 对象取 stage / 空对象返回 null / null 返回 null
 * 3. 新增块类型逐一渲染：api_table / kpi_grid / conflicts / risks / timeline /
 *    data_model / test_groups / file_tree / team_config / service_viewer
 * 4. risks 空列表返回 null（边界）
 * 5. raw 块走 Markdown 渲染（后端约定）
 * 6. 未知类型兜底：有文本渲染、无文本返回 null（防静默丢失）
 * 7. ReportLayoutRenderer：null layout 返回 null；空 sections 显示占位文案
 */
import { describe, it, expect } from 'vitest';
import { screen, render } from '@testing-library/react';
import {
  ReportBlockRenderer,
  ReportLayoutRenderer,
  type LayoutBlock,
} from '@/components/report/report-block-renderer';
import { parseApiEndpoint, formatTrace } from '@/components/report/report-block-utils';

const renderBlock = (block: LayoutBlock) => render(<ReportBlockRenderer block={block} />);

describe('parseApiEndpoint', () => {
  it('解析"方法 路径 - 说明"完整格式', () => {
    expect(parseApiEndpoint('GET /api/users - 获取用户列表')).toEqual({
      method: 'GET',
      path: '/api/users',
      desc: '获取用户列表',
    });
  });

  it('无方法前缀时整段作为路径（边界）', () => {
    expect(parseApiEndpoint('/api/health - 健康检查')).toEqual({
      method: '',
      path: '/api/health',
      desc: '健康检查',
    });
  });

  it('无说明分隔符时 desc 为空', () => {
    expect(parseApiEndpoint('POST /api/users')).toEqual({ method: 'POST', path: '/api/users', desc: '' });
  });

  it('单段文本整体作为路径（边界）', () => {
    expect(parseApiEndpoint('weird-endpoint')).toEqual({ method: '', path: 'weird-endpoint', desc: '' });
  });
});

describe('formatTrace', () => {
  it('字符串原样返回', () => {
    expect(formatTrace('来自 discuss 阶段')).toBe('来自 discuss 阶段');
  });

  it('对象优先取 stage/description 字段', () => {
    expect(formatTrace({ stage: 'discuss', description: '第二轮辩论' })).toBe('discuss · 第二轮辩论');
  });

  it('空对象/空字符串/null 返回 null（异常路径）', () => {
    expect(formatTrace({})).toBeNull();
    expect(formatTrace('   ')).toBeNull();
    expect(formatTrace(null)).toBeNull();
    expect(formatTrace(undefined)).toBeNull();
  });
});

describe('ReportBlockRenderer 新增块类型', () => {
  it('api_table 渲染方法徽标、路径与说明', () => {
    renderBlock({
      type: 'api_table',
      data: { endpoints: ['GET /api/users - 获取用户列表', 'POST /api/users - 创建用户'] },
    });
    expect(screen.getByText('GET')).toBeDefined();
    expect(screen.getByText('POST')).toBeDefined();
    // 两行端点路径相同，用 getAllByText 断言数量
    expect(screen.getAllByText('/api/users', { selector: 'td' })).toHaveLength(2);
    expect(screen.getByText('获取用户列表')).toBeDefined();
  });

  it('api_table 空端点列表返回 null（边界）', () => {
    const { container } = renderBlock({ type: 'api_table', data: { endpoints: [] } });
    expect(container.innerHTML).toBe('');
  });

  it('kpi_grid 渲染数值、单位与标签', () => {
    renderBlock({
      type: 'kpi_grid',
      data: { items: [{ label: '转化率', value: '12.5', unit: '%', trend: '↑ 2%' }] },
    });
    expect(screen.getByText('12.5')).toBeDefined();
    expect(screen.getByText('%')).toBeDefined();
    expect(screen.getByText('转化率')).toBeDefined();
  });

  it('conflicts 渲染双方观点与裁决徽标', () => {
    renderBlock({
      type: 'conflicts',
      data: {
        items: [
          { summary: '技术选型分歧', sideA: '用 PostgreSQL', sideB: '用 MySQL', verdict: 'a', rationale: '生态更成熟' },
        ],
      },
    });
    expect(screen.getByText('技术选型分歧')).toBeDefined();
    expect(screen.getByText('用 PostgreSQL')).toBeDefined();
    expect(screen.getByText('采纳 A')).toBeDefined();
    expect(screen.getByText(/生态更成熟/)).toBeDefined();
  });

  it('risks 按等级渲染徽标文案', () => {
    renderBlock({
      type: 'risks',
      data: {
        items: [
          { level: 'high', desc: '数据丢失风险' },
          { level: 'low', desc: '界面微调' },
        ],
      },
    });
    expect(screen.getByText('高')).toBeDefined();
    expect(screen.getByText('低')).toBeDefined();
    expect(screen.getByText('数据丢失风险')).toBeDefined();
  });

  it('risks 空列表返回 null（边界）', () => {
    const { container } = renderBlock({ type: 'risks', data: { items: [] } });
    expect(container.innerHTML).toBe('');
  });

  it('timeline 渲染日期与事件', () => {
    renderBlock({
      type: 'timeline',
      data: { items: [{ date: '2026-09-01', text: '项目启动' }] },
    });
    expect(screen.getByText('2026-09-01')).toBeDefined();
    expect(screen.getByText('项目启动')).toBeDefined();
  });

  it('data_model 渲染实体名与字段', () => {
    renderBlock({
      type: 'data_model',
      data: { entities: [{ entity: 'users', fields: ['id [PK]', 'name'] }] },
    });
    expect(screen.getByText('users')).toBeDefined();
    expect(screen.getByText('id [PK]')).toBeDefined();
  });

  it('test_groups 渲染通过/失败统计与用例行', () => {
    renderBlock({
      type: 'test_groups',
      data: {
        tests: [
          { name: 'test_register_ok', result: 'pass', time: '0.12s' },
          { name: 'test_register_dup', result: 'fail', time: '0.30s' },
        ],
      },
    });
    expect(screen.getByText('test_register_ok')).toBeDefined();
    expect(screen.getByText('通过')).toBeDefined();
    expect(screen.getByText('失败')).toBeDefined();
    expect(screen.getByText('0.12s')).toBeDefined();
  });

  it('file_tree 渲染目录与文件', () => {
    renderBlock({
      type: 'file_tree',
      data: {
        items: [
          { name: 'app', type: 'dir', indent: 0 },
          { name: 'main.py', type: 'file', indent: 1 },
        ],
      },
    });
    // 目录带斜杠后缀
    expect(screen.getByText('app/')).toBeDefined();
    expect(screen.getByText('main.py')).toBeDefined();
  });

  it('team_config 渲染角色与立场', () => {
    renderBlock({
      type: 'team_config',
      data: { items: [{ role: '架构师', stance: '主张微服务拆分' }] },
    });
    expect(screen.getByText('架构师')).toBeDefined();
    expect(screen.getByText('主张微服务拆分')).toBeDefined();
  });

  it('service_viewer 渲染端口、启动命令与代码', () => {
    renderBlock({
      type: 'service_viewer',
      data: { title: '演示服务', port: 8000, run_command: 'python main.py', app_code: 'print("hi")' },
    });
    expect(screen.getByText('端口 8000')).toBeDefined();
    expect(screen.getByText('python main.py')).toBeDefined();
    expect(screen.getByText('print("hi")')).toBeDefined();
  });
});

describe('ReportBlockRenderer 兼容与兜底', () => {
  it('raw 块按 Markdown 渲染（后端约定：raw = 待处理 Markdown）', () => {
    const { container } = renderBlock({ type: 'raw', data: { text: '**重点**结论' } });
    // Markdown 渲染出 <strong>，而非 mono 纯文本
    expect(container.querySelector('strong')).not.toBeNull();
    expect(screen.getByText('重点')).toBeDefined();
  });

  it('paragraph 块走 Markdown 渲染', () => {
    const { container } = renderBlock({ type: 'paragraph', data: { text: '第一段\n第二段' } });
    expect(container.querySelector('.prose-conclave')).not.toBeNull();
  });

  it('未知类型有文本时兜底渲染（防静默丢失）', () => {
    renderBlock({ type: 'future_block', data: { text: '兜底内容' } });
    expect(screen.getByText('兜底内容')).toBeDefined();
  });

  it('未知类型无任何可展示内容时返回 null', () => {
    const { container } = renderBlock({ type: 'future_block', data: {} });
    expect(container.innerHTML).toBe('');
  });
});

describe('ReportLayoutRenderer', () => {
  it('null layout 返回 null', () => {
    const { container } = render(<ReportLayoutRenderer layout={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('空 sections 显示占位文案', () => {
    render(<ReportLayoutRenderer layout={{ sections: [] }} />);
    expect(screen.getByText('暂无结构化报告内容')).toBeDefined();
  });

  it('渲染章节标题与内部块', () => {
    render(
      <ReportLayoutRenderer
        layout={{
          sections: [
            {
              id: 'risks',
              title: '风险评估',
              blocks: [{ type: 'risks', data: { items: [{ level: 'high', desc: '关键风险' }] } }],
            },
          ],
        }}
      />,
    );
    expect(screen.getByText('风险评估')).toBeDefined();
    expect(screen.getByText('关键风险')).toBeDefined();
  });
});
