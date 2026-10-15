import Footer from '@/components/Footer';
import RightContent from '@/components/RightContent';
import {PageLoading, Settings as LayoutSettings} from '@ant-design/pro-components';
import {SettingDrawer} from '@ant-design/pro-components';
import type {RunTimeLayoutConfig} from '@umijs/max';
import {history} from '@umijs/max';
import defaultSettings from '../config/defaultSettings';
import {errorConfig} from './requestErrorConfig';
import {currentUser as queryCurrentUser, LoginUser} from './services/auth';
import React from 'react';
import NoTableData from "@/assets/NoSearch.svg";

import {ConfigProvider, Empty, message, Spin} from "antd";
import IndexPage from "@/pages/IndexPage";
import { Loading } from '@icon-park/react';

const isDev = process.env.NODE_ENV === 'development';
const loginPath = '/user/login';
Spin.setDefaultIndicator(<Loading spin={true} theme="outline" size="36" fill="#4a90e2" strokeLinecap="butt" />)

// 静默 umi-plugin-locale / react-intl 在控制台抛的"Missing message"噪音。
// zh-CN 字典是 ant-design-pro 模板的精简版(53 行 menu key),远低于 ProLayout/ProComponents
// 内置的完整 key 集(tabs.refresh / menu.project 等)。运行时已有 fallback(显示 key 字符串,
// 对菜单来说就是显示中文名),UI 完全不受影响,只是不要让 [React Intl] 报错刷屏。
// 同时屏蔽 SelectLang 在浏览器 locale 不匹配任何一种语言时的 warning。
const _intlOriginalConsoleError = console.error;
console.error = (...args: unknown[]) => {
  const msg = typeof args[0] === 'string' ? args[0] : '';
  if (
    msg.startsWith('[React Intl]') ||
    msg.includes('The current popular language does not exist')
  ) {
    return;
  }
  _intlOriginalConsoleError(...args);
};

/**
 * @see  https://umijs.org/zh-CN/plugins/plugin-initial-state
 * */
export async function getInitialState(): Promise<{
  settings?: Partial<LayoutSettings>;
  currentUser?: LoginUser;
  loading?: boolean;
  fetchUserInfo?: () => Promise<LoginUser | undefined>;
}> {
  const fetchUserInfo = async () => {
    try {
      const token = localStorage.getItem("pityToken");
      if (!token) {
        history.push(loginPath);
        return;
      }
      const msg = await queryCurrentUser({token});
      if (msg.code !== 0) {
        message.info(msg.msg);
        throw msg.msg;
      }
      return msg.data;
    } catch (error) {
      history.push(loginPath);
    }
    return undefined;
  };
  // 如果不是登录页面，执行
  const {location} = history;
  if (location.pathname !== loginPath) {
    const currentUser = await fetchUserInfo();
    return {
      fetchUserInfo,
      currentUser,
      settings: defaultSettings,
    };
  }

  return {
    fetchUserInfo,
    settings: defaultSettings,
  };
}

// ProLayout 支持的api https://procomponents.ant.design/components/layout
export const layout: RunTimeLayoutConfig = ({initialState, setInitialState}) => {
  return {
    siderWidth: 216,
    rightContentRender: () => <RightContent/>,
    waterMarkProps: {
      content: initialState?.currentUser?.name,
    },
    footerRender: () => <Footer/>,
    onPageChange: () => {
      const {location} = history;
      // 如果没有登录，重定向到 login
      if (!initialState?.currentUser && location.pathname !== loginPath) {
        history.push(loginPath);
      }
    },
    layoutBgImgList: [
      {
        src: 'https://img.alicdn.com/imgextra/i2/O1CN01O4etvp1DvpFLKfuWq_!!6000000000279-2-tps-609-606.png',
        left: 85,
        bottom: 100,
        height: '303px',
      },
      {
        src: 'https://img.alicdn.com/imgextra/i2/O1CN01O4etvp1DvpFLKfuWq_!!6000000000279-2-tps-609-606.png',
        bottom: -68,
        right: -45,
        height: '303px',
      },
      {
        src: 'https://img.alicdn.com/imgextra/i3/O1CN018NxReL1shX85Yz6Cx_!!6000000005798-2-tps-884-496.png',
        bottom: 0,
        left: 0,
        width: '331px',
      },
    ],
    links: [],
    menuHeaderRender: undefined,
    // 自定义 403 页面
    // unAccessible: <div>unAccessible</div>,
    // 增加一个 loading 的状态
    childrenRender: (children) => {
      if (initialState?.loading) return <PageLoading/>;
      return (
        <ConfigProvider
        renderEmpty={() => <Empty image={NoTableData} styles={{image: {height: 160}}}
                                                  description="暂无数据"/>}>
          {children}
          <IndexPage/>
          <SettingDrawer
            disableUrlParams
            enableDarkTheme
            settings={initialState?.settings}
            onSettingChange={(settings) => {
              setInitialState((preInitialState) => ({
                ...preInitialState,
                settings,
              }));
            }}
          />
        </ConfigProvider>
      );
    },
    ...initialState?.settings,
  };
};

/**
 * @name request 配置，可以配置错误处理
 * 它基于 axios 和 ahooks 的 useRequest 提供了一套统一的网络请求和错误处理方案。
 * @doc https://umijs.org/docs/max/request#配置
 */
export const request = {
  ...errorConfig,
};
