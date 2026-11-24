/**
 * `ToolShell` 组件 smoke test —— 12 个工具页共用的外壳。
 *
 * 只验证结构与文案透传, 不测样式: 外壳一旦渲染崩, 所有工具页一起白屏。
 */
import React from 'react';
import { render, screen } from '@testing-library/react';

import { ToolLabel, ToolResult, ToolShell } from '@/components/Tool/ToolShell';

describe('ToolShell', () => {
  test('渲染标题与内容', () => {
    render(
      <ToolShell title="JSON 格式化">
        <div data-testid="body">内容区</div>
      </ToolShell>,
    );
    expect(screen.getByText('JSON 格式化')).toBeTruthy();
    expect(screen.getByTestId('body')).toBeTruthy();
    expect(screen.getByText('内容区')).toBeTruthy();
  });

  test('description 可选, 传了才渲染', () => {
    const { rerender } = render(<ToolShell title="标题">x</ToolShell>);
    expect(screen.queryByText('副标题')).toBeNull();

    rerender(
      <ToolShell title="标题" description="副标题">
        x
      </ToolShell>,
    );
    expect(screen.getByText('副标题')).toBeTruthy();
  });

  test('extra 插槽渲染在卡片头部', () => {
    render(
      <ToolShell title="标题" extra={<button type="button">复制</button>}>
        x
      </ToolShell>,
    );
    expect(screen.getByText('复制')).toBeTruthy();
  });
});

describe('ToolLabel / ToolResult', () => {
  test('ToolLabel 渲染分组标签', () => {
    render(<ToolLabel>字段展开</ToolLabel>);
    expect(screen.getByText('字段展开')).toBeTruthy();
  });

  test('ToolResult 有值时展示输出文本', () => {
    render(<ToolResult value={'{"a":1}'} />);
    expect(screen.getByText('{"a":1}')).toBeTruthy();
    expect(screen.getByText('结果')).toBeTruthy();
  });

  test('ToolResult 空值显示默认占位文案而不是空白', () => {
    render(<ToolResult value="" />);
    expect(screen.getByText('等待输入')).toBeTruthy();
  });

  test('emptyText 可覆盖', () => {
    render(<ToolResult value="" emptyText="输入表达式后这里会出结果" />);
    expect(screen.getByText('输入表达式后这里会出结果')).toBeTruthy();
  });

  test('notice 渲染为 Alert(错误提示的关键通路)', () => {
    render(<ToolResult value="" notice={{ type: 'error', text: '解析失败' }} />);
    expect(screen.getByText('解析失败')).toBeTruthy();
  });

  test('label 可覆盖', () => {
    render(<ToolResult value="x" label="下次触发" />);
    expect(screen.getByText('下次触发')).toBeTruthy();
  });
});
