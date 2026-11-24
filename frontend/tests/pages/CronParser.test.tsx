/**
 * `pages/Tool/CronParser` 页面 smoke test —— 依赖最少的工具页(无 request / 无 model)。
 *
 * 覆盖三条主通路: 合法表达式出结果、非法表达式出错误、预设一键填入。
 * 时间相关的断言一律不写死日期(页面内部用 `new Date()`), 只验结构与文案。
 */
import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import CronParser from '@/pages/Tool/CronParser';

describe('CronParser 页面', () => {
  test('首屏渲染标题、说明与默认表达式', () => {
    render(<CronParser />);
    expect(screen.getByText('Cron 表达式解析')).toBeTruthy();
    expect(screen.getByText(/支持 5 段/)).toBeTruthy();
    // 默认值是工作日 09:00, 直接进输入框
    expect((screen.getByPlaceholderText('0 9 * * 1-5') as HTMLInputElement).value).toBe(
      '0 9 * * 1-5',
    );
    // 默认表达式合法 → 不该出现错误条
    expect(screen.queryByText('表达式不合法')).toBeNull();
  });

  test('合法表达式渲染字段展开与下次触发', () => {
    render(<CronParser />);
    expect(screen.getByText('字段展开')).toBeTruthy();
    expect(screen.getByText('接下来 5 次触发(本地时间)')).toBeTruthy();
    // 5 个字段标签
    for (const name of ['分', '时', '日', '月', '周']) {
      expect(screen.getAllByText(name).length).toBeGreaterThan(0);
    }
  });

  test('非法表达式显示错误条与原因', () => {
    render(<CronParser />);
    const input = screen.getByPlaceholderText('0 9 * * 1-5');
    fireEvent.change(input, { target: { value: '60 * * * *' } });
    expect(screen.getByText('表达式不合法')).toBeTruthy();
    // 断言具体原因, 不用 /分/ —— 「分」在字段标签与说明文案里到处都是
    expect(screen.getByText(/超出范围/)).toBeTruthy();
    expect(screen.queryByText('字段展开')).toBeNull();
  });

  test('Quartz 语法被拒绝并说明原因(不静默降级)', () => {
    render(<CronParser />);
    fireEvent.change(screen.getByPlaceholderText('0 9 * * 1-5'), {
      target: { value: '0 0 L * *' },
    });
    expect(screen.getByText('表达式不合法')).toBeTruthy();
    expect(screen.getByText(/Quartz/)).toBeTruthy();
  });

  test('清空按钮把输入置空并变为禁用', () => {
    render(<CronParser />);
    // 用「去空白后相等」的匹配函数: antd Button 在 jsdom 下取出的文本会带空白,
    // 精确字符串与 getByRole({name}) 都会匹配失败(失败时还会 dump 整个 DOM, 本例曾耗时 500s+)。
    const clearBtn = () =>
      screen
        .getByText((content) => content.replace(/\s/g, '') === '清空')
        .closest('button') as HTMLButtonElement;
    expect(clearBtn().disabled).toBe(false);

    fireEvent.click(clearBtn());
    expect((screen.getByPlaceholderText('0 9 * * 1-5') as HTMLInputElement).value).toBe('');
    expect(clearBtn().disabled).toBe(true);
    // 空输入也走错误通路
    expect(screen.getByText('表达式不合法')).toBeTruthy();
  });

  test('点击预设标签一键填入', () => {
    render(<CronParser />);
    fireEvent.change(screen.getByPlaceholderText('0 9 * * 1-5'), { target: { value: '' } });
    expect(screen.getByText('表达式不合法')).toBeTruthy();

    // 「每小时整点」预设
    fireEvent.click(screen.getByText(/每小时整点/));
    expect((screen.getByPlaceholderText('0 9 * * 1-5') as HTMLInputElement).value).toBe(
      '0 * * * *',
    );
    expect(screen.queryByText('表达式不合法')).toBeNull();
    expect(screen.getByText('字段展开')).toBeTruthy();
  });

  test('预设区渲染全部速查项', () => {
    render(<CronParser />);
    expect(screen.getByText('常用表达式(点击填入)')).toBeTruthy();
    expect(screen.getByText(/每分钟/)).toBeTruthy();
    expect(screen.getByText(/每 10 秒/)).toBeTruthy();
  });
});
