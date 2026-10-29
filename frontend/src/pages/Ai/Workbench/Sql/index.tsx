import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { useModel } from '@umijs/max';
import { fetchDatabaseSource, onlineExecuteSQL } from '@/services/online';
import { AiSlowSql, AiSqlAnalysis } from '@/services/aiWorkbench';

const { Text, Paragraph } = Typography;

const LEVEL_COLORS: Record<string, string> = { high: 'red', medium: 'orange', low: 'blue' };
const LEVEL_LABELS: Record<string, string> = { high: '严重', medium: '一般', low: '轻微' };

/**
 * SQL 分析
 *
 * 左边是慢查询排行与待分析的 SQL, 右边是分析结果。
 *
 * **只读保证**: 后端采集执行计划时只发普通 `EXPLAIN`, 绝不执行目标 SQL ——
 * `EXPLAIN ANALYZE` 在解析层就被拦下。
 *
 * 改写后的 SQL 可以一键「执行验证」—— 复用既有的 `POST /online/sql`。
 */
const SqlPage: React.FC = () => {
  const { models, generatingSql, analyzeSql, fetchSlowSqls } = useModel('aiWorkbench');

  const [databases, setDatabases] = useState<any[]>([]);
  const [databaseId, setDatabaseId] = useState<number | undefined>();
  const [sql, setSql] = useState('');
  const [slowList, setSlowList] = useState<AiSlowSql[]>([]);
  const [result, setResult] = useState<AiSqlAnalysis | null>(null);
  const [error, setError] = useState('');
  const [vendorId, setVendorId] = useState<number | undefined>();
  const [modelId, setModelId] = useState<number | undefined>();
  const [verifyResult, setVerifyResult] = useState('');

  useEffect(() => {
    fetchDatabaseSource({})
      .then((res: any) => {
        if (res?.code === 0) {
          const list = res.data || [];
          setDatabases(list);
          if (list.length > 0) setDatabaseId(list[0].id);
        }
      })
      .catch(() => undefined);
  }, []);

  const modelOptions = useMemo(() => {
    const vendor = models.find((item) => item.vendor_id === vendorId);
    return (vendor?.models || []).map((item) => ({ label: item.model_name, value: item.model_id }));
  }, [models, vendorId]);

  const databaseOptions = useMemo(
    () =>
      databases.map((item: any) => ({
        label: item.name || `数据库 ${item.id}`,
        value: item.id,
      })),
    [databases],
  );

  const loadSlow = async () => {
    const list = await fetchSlowSqls({ database_id: databaseId, page: 1, size: 20 });
    if (list) setSlowList(list as AiSlowSql[]);
  };

  useEffect(() => {
    if (databaseId) loadSlow();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [databaseId]);

  const handleAnalyze = async (target?: string) => {
    const text = target ?? sql;
    if (!text || !text.trim()) {
      message.warning('请填写要分析的 SQL, 或从慢查询列表里选一条');
      return;
    }
    if (!databaseId) {
      message.warning('请先选择数据库');
      return;
    }
    if (!vendorId || !modelId) {
      message.warning('请先选择模型');
      return;
    }
    setError('');
    setVerifyResult('');
    try {
      const data: any = await analyzeSql({ sql: text, database_id: databaseId, vendor_id: vendorId, model_id: modelId });
      if (data) setResult(data);
    } catch (e: any) {
      setError(e?.msg || e?.message || '分析失败, 请重试');
    }
  };

  const handleVerify = async () => {
    if (!result?.rewritten_sql || !databaseId) return;
    const res: any = await onlineExecuteSQL({ id: databaseId, sql: result.rewritten_sql });
    if (res?.code === 0) {
      const data = res.data || {};
      setVerifyResult(`执行成功, 耗时 ${data.elapsed} ms\n${JSON.stringify(data.result, null, 2)}`);
    } else {
      setVerifyResult(`执行失败: ${res?.msg || '未知错误'}`);
    }
  };

  return (
    <div className="ai-workbench-page">
      <Row gutter={12}>
        <Col xs={24} xl={8}>
          <Card bordered={false} title="分析输入">
            <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
              <Select
                style={{ flex: 1 }}
                placeholder="选择数据库"
                value={databaseId}
                options={databaseOptions}
                onChange={setDatabaseId}
              />
              <Select
                style={{ flex: 1 }}
                placeholder="选择厂商"
                value={vendorId}
                options={models.map((item) => ({ label: item.vendor_name, value: item.vendor_id }))}
                onChange={(value) => {
                  setVendorId(value);
                  setModelId(undefined);
                }}
              />
            </Space.Compact>
            <Select
              style={{ width: '100%', marginBottom: 12 }}
              placeholder="选择模型"
              value={modelId}
              disabled={!vendorId}
              options={modelOptions}
              onChange={setModelId}
            />
            <Input.TextArea
              rows={10}
              placeholder="要分析的 SQL"
              value={sql}
              onChange={(e) => setSql(e.target.value)}
              style={{ fontFamily: 'monospace' }}
            />
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 8, marginBottom: 12 }}
              message="只采集执行计划, 不执行这条 SQL"
              description="执行计划用普通 EXPLAIN 采集, EXPLAIN ANALYZE 在解析层就被拦下。"
            />
            <Button type="primary" block loading={generatingSql} onClick={() => handleAnalyze()}>
              开始分析
            </Button>
            {error ? (
              <Alert type="error" showIcon style={{ marginTop: 12 }} message={error} />
            ) : null}
          </Card>

          <Card
            bordered={false}
            title="慢查询排行"
            extra={
              <Button size="small" type="text" onClick={loadSlow}>
                刷新
              </Button>
            }
          >
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={slowList}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有慢查询记录" /> }}
              columns={[
                {
                  title: '耗时',
                  dataIndex: 'elapsed',
                  width: 80,
                  render: (value: number) => <Tag color={value > 1000 ? 'red' : 'orange'}>{value} ms</Tag>,
                },
                {
                  title: 'SQL',
                  dataIndex: 'sql',
                  ellipsis: true,
                  render: (value: string) => (
                    <a onClick={() => handleAnalyze(value)}>
                      <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: value }}>
                        {value}
                      </Text>
                    </a>
                  ),
                },
              ]}
            />
          </Card>
        </Col>

        <Col xs={24} xl={16}>
          <Spin spinning={generatingSql}>
            <Card bordered={false} title="分析结果">
              {!result ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="还没有分析结果 —— 填一条 SQL 或从慢查询列表里选一条"
                />
              ) : (
                <div>
                  <Space style={{ marginBottom: 12 }}>
                    <Tag>可信度 {(result.confidence * 100).toFixed(0)}%</Tag>
                    {result.elapsed_ms ? <Tag>采集耗时 {result.elapsed_ms} ms</Tag> : null}
                    {result.table_refs?.map((item) => (
                      <Tag key={item}>{item}</Tag>
                    ))}
                  </Space>

                  {result.problems?.length ? (
                    <>
                      <Paragraph strong>问题点</Paragraph>
                      {result.problems.map((item, index) => (
                        <Card key={index} size="small" style={{ marginBottom: 8 }}>
                          <Space style={{ marginBottom: 4 }}>
                            <Tag color={LEVEL_COLORS[item.level] || 'default'}>
                              {LEVEL_LABELS[item.level] || item.level}
                            </Tag>
                            <Text strong>{item.point}</Text>
                          </Space>
                          <Paragraph style={{ marginBottom: 0 }}>{item.detail}</Paragraph>
                        </Card>
                      ))}
                    </>
                  ) : null}

                  {result.index_suggestions?.length ? (
                    <>
                      <Paragraph strong>索引建议</Paragraph>
                      {result.index_suggestions.map((item, index) => (
                        <Card key={index} size="small" style={{ marginBottom: 8 }}>
                          <Paragraph style={{ marginBottom: 4 }}>{item.reason}</Paragraph>
                          <pre style={{ margin: 0 }}>{item.ddl}</pre>
                        </Card>
                      ))}
                    </>
                  ) : null}

                  {result.rewritten_sql ? (
                    <>
                      <Space style={{ marginTop: 8 }}>
                        <Paragraph strong style={{ marginBottom: 4 }}>
                          改写 SQL
                        </Paragraph>
                        <Button size="small" onClick={handleVerify}>
                          执行验证
                        </Button>
                      </Space>
                      <pre>{result.rewritten_sql}</pre>
                    </>
                  ) : null}

                  {verifyResult ? (
                    <Alert
                      type={verifyResult.startsWith('执行成功') ? 'success' : 'error'}
                      showIcon
                      style={{ marginTop: 12 }}
                      message={verifyResult.split('\n')[0]}
                      description={
                        verifyResult.includes('\n') ? <pre>{verifyResult.split('\n').slice(1).join('\n')}</pre> : null
                      }
                    />
                  ) : null}

                  {result.plan?.length ? (
                    <>
                      <Paragraph strong style={{ marginTop: 12 }}>
                        执行计划
                      </Paragraph>
                      <Table
                        rowKey={(row: any, index?: number) => `${index}`}
                        size="small"
                        pagination={false}
                        dataSource={result.plan}
                        columns={Object.keys(result.plan[0] || {}).map((key) => ({
                          title: key,
                          dataIndex: key,
                          ellipsis: true,
                        }))}
                      />
                    </>
                  ) : null}
                </div>
              )}
            </Card>
          </Spin>
        </Col>
      </Row>
    </div>
  );
};

export default SqlPage;
