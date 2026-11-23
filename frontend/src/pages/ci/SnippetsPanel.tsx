import React, { useMemo, useState } from 'react';
import { Alert, Button, Empty, Select, Space, Tabs, Typography } from 'antd';
import { CopyOutlined } from '@ant-design/icons';
import { useModel } from '@umijs/max';
import CONFIG from '@/consts/config';
import { CI_TOKEN_PLACEHOLDER } from '@/consts/ci';

const { Text } = Typography;

/**
 * 接入示例面板(spec US4)
 *
 * **片段是要被粘进 Git 仓库的** —— 所以凭据位置**恒为占位符** `YOUR_PITY_CI_TOKEN`,
 * 绝不回显真实明文(否则等于教用户把凭据提交进代码库)。平台地址与 plan_id
 * **可以**自动填(它们不是秘密), 这样复制出去基本可直接用。
 *
 * G2: 未选集成配置 → 提示先创建; G3: 项目下无计划 → 提示先建计划。
 */
const SnippetsPanel: React.FC = () => {
  const { projectId, integrations, plans } = useModel('ci');
  const [integrationId, setIntegrationId] = useState<number | undefined>();
  const [copied, setCopied] = useState<string | null>(null);

  const selected = integrations.find((i) => i.id === integrationId) ?? integrations[0];
  const selectedPlanId = selected?.plan_id ?? plans[0]?.id;
  const selectedPlanName = plans.find((p) => p.id === selectedPlanId)?.name;

  const planIdForSnippet = useMemo(() => selectedPlanId ?? 0, [selectedPlanId]);

  const jenkinsfile = useMemo(
    () => `stage('Pity 测试') {
  steps {
    script {
      def resp = httpRequest url: "\${PITY_URL}/ci/run",
        httpMode: 'POST',
        contentType: 'APPLICATION_JSON',
        customHeaders: [[name: 'token', value: '${CI_TOKEN_PLACEHOLDER}', maskValue: true]],
        requestBody: '{"plan_id": ${planIdForSnippet}, "external_build_id": "\${BUILD_NUMBER}", "wait": true, "timeout_sec": 300}'
      def body = readJSON text: resp.content
      // 0 通过 / 111 未通过 / 112 超时 → 其余一律阻断
      if (body.code != 0) { error("Pity: \${body.msg}") }
    }
  }
}`,
    [planIdForSnippet],
  );

  const ghActions = useMemo(
    () => `- name: Pity 测试
  env:
    PITY_URL: ${CONFIG.URL}
  run: |
    CODE=$(curl -sS -X POST "\${PITY_URL}/ci/run" \\
      -H "token: ${CI_TOKEN_PLACEHOLDER}" -H "Content-Type: application/json" \\
      -d '{"plan_id": ${planIdForSnippet}, "external_build_id": "\${GITHUB_RUN_NUMBER}", "wait": true, "timeout_sec": 300}' \\
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["code"])')
    echo "pity code=\${CODE}"
    # 0 通过 / 111 未通过 / 112 超时 / 其余一律阻断
    [ "\${CODE}" = "0" ] || exit 1`,
    [planIdForSnippet],
  );

  const copy = async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      /* 剪贴板不可用时用户仍可手动选中 */
    }
  };

  if (!projectId) {
    return <Empty description="请先选择项目" />;
  }

  // G3: 没有计划就没有可触发的对象 —— 硬前置
  if (plans.length === 0) {
    return (
      <Alert
        showIcon
        type="warning"
        message="本项目还没有测试计划"
        description="接入示例需要一个可触发的计划 ID。请先创建测试计划，再回到这里复制片段。"
      />
    );
  }

  // G2: 没有凭据，片段抄出去也调不通
  if (integrations.length === 0) {
    return (
      <Alert
        showIcon
        type="warning"
        message="本项目还没有接入凭据"
        description="请先到「集成配置」签发一条凭据，并把明文存进流水线的凭据管理（Jenkins Credentials / GitHub Secrets）。"
      />
    );
  }

  const SnippetBlock: React.FC<{
    id: string;
    title: string;
    code: string;
    tip: string;
  }> = ({ id, title, code, tip }) => (
    <div className="ci-snippet">
      <Space style={{ marginBottom: 8 }}>
        <Text strong>{title}</Text>
        <Button
          size="small"
          icon={<CopyOutlined />}
          onClick={() => copy(id, code)}
          type={copied === id ? 'primary' : 'default'}
        >
          {copied === id ? '已复制' : '复制'}
        </Button>
      </Space>
      <pre>{code}</pre>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {tip}
      </Text>
    </div>
  );

  return (
    <div>
      <Alert
        showIcon
        type="info"
        style={{ marginBottom: 16 }}
        message="凭据用占位符，不要把明文粘进仓库"
        description={
          <>
            片段里的 <Text code>{CI_TOKEN_PLACEHOLDER}</Text> 需要替换成你在「集成配置」
            签发的凭据，并存进流水线的密钥管理。平台地址与计划 ID 已按当前选择自动填好
            {selectedPlanName ? `（计划：${selectedPlanName}）` : ''}。
          </>
        }
      />

      <Space style={{ marginBottom: 16 }}>
        <Text>使用哪条凭据：</Text>
        <Select
          style={{ minWidth: 260 }}
          value={selected?.id}
          onChange={setIntegrationId}
          options={integrations.map((i) => ({
            label: `${i.name}（${i.token_prefix}…）`,
            value: i.id,
          }))}
        />
      </Space>

      <Tabs
        items={[
          {
            key: 'jenkins',
            label: 'Jenkinsfile',
            children: (
              <SnippetBlock
                id="jenkins"
                title="Jenkinsfile 片段"
                code={jenkinsfile}
                tip="需要 Generic Webhook Trigger 或 HTTP Request 插件；把 PITY_URL 与凭据放进 Jenkins Credentials。"
              />
            ),
          },
          {
            key: 'gha',
            label: 'GitHub Actions',
            children: (
              <SnippetBlock
                id="gha"
                title="GitHub Actions 工作流片段"
                code={ghActions}
                tip="把凭据存成仓库 Secret：PITY_CI_TOKEN。"
              />
            ),
          },
        ]}
      />
    </div>
  );
};

export default SnippetsPanel;
