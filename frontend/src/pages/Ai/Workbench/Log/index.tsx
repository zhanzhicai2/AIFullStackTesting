import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import { useModel } from '@umijs/max';
import { AiErrorCluster, AiLogSpike } from '@/services/aiWorkbench';

const { Text, Paragraph } = Typography;

/**
 * 日志分析
 *
 * 左边选来源与日志, 右边是**错误簇列表**(纯确定性聚类的结果, 不调模型)。
 * 每个簇可以单独发起归因 —— 那一步才调模型。
 */
const LogPage: React.FC = () => {
  const { models, generatingLog, clusterLogs, analyzeCluster, fetchModels } = useModel('aiWorkbench');

  const [source, setSource] = useState<string>('text');
  const [text, setText] = useState('');
  const [fileId, setFileId] = useState<number | undefined>();
  const [clusters, setClusters] = useState<AiErrorCluster[]>([]);
  const [spikes, setSpikes] = useState<AiLogSpike[]>([]);
  const [totalLines, setTotalLines] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState('');
  const [attribution, setAttribution] = useState<Record<string, any>>({});
  const [vendorId, setVendorId] = useState<number | undefined>();
  const [modelId, setModelId] = useState<number | undefined>();

  useEffect(() => {
    fetchModels();
  }, [fetchModels]);

  const modelOptions = useMemo(() => {
    const vendor = models.find((item) => item.vendor_id === vendorId);
    return (vendor?.models || []).map((item) => ({ label: item.model_name, value: item.model_id }));
  }, [models, vendorId]);

  const handleCluster = async () => {
    setError('');
    setAttribution({});
    try {
      const data: any = await clusterLogs({
        source,
        text: source === 'text' ? text : undefined,
        file_id: source === 'file' ? fileId : undefined,
      });
      if (data) {
        setClusters(data.error_clusters || []);
        setSpikes(data.spikes || []);
        setTotalLines(data.total_lines || 0);
        setTruncated(!!data.truncated);
      }
    } catch (e: any) {
      setError(e?.msg || e?.message || '聚类失败, 请重试');
    }
  };

  const handleAnalyze = async (record: AiErrorCluster) => {
    if (!vendorId || !modelId) {
      message.warning('请先选择模型');
      return;
    }
    try {
      const data: any = await analyzeCluster({
        fingerprint: record.fingerprint,
        samples: record.sample ? record.sample.split('\n') : [],
        count: record.count,
        vendor_id: vendorId,
        model_id: modelId,
      });
      if (data) {
        setAttribution((prev) => ({ ...prev, [record.fingerprint]: data }));
      }
    } catch (e: any) {
      message.error(e?.msg || e?.message || '归因失败');
    }
  };

  const columns = [
    {
      title: '错误簇',
      dataIndex: 'fingerprint',
      width: 110,
      render: (value: string) => <Text code>{value}</Text>,
    },
    { title: '次数', dataIndex: 'count', width: 80 },
    {
      title: '首次 / 末次出现',
      dataIndex: 'first_at',
      width: 200,
      render: (value: string, record: AiErrorCluster) => (
        <span style={{ fontSize: 12 }}>
          {value || '-'}
          <br />
          {record.last_at || '-'}
        </span>
      ),
    },
    {
      title: '影响范围',
      dataIndex: 'scope',
      width: 130,
      render: (value: any) => (
        <Space size={4}>
          <Tag>用例 {value?.cases ?? 0}</Tag>
          <Tag>用户 {value?.users ?? 0}</Tag>
        </Space>
      ),
    },
    {
      title: '样例',
      dataIndex: 'sample',
      ellipsis: true,
      render: (value: string) => (
        <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: value }}>
          {value}
        </Text>
      ),
    },
    {
      title: '操作',
      key: 'op',
      width: 90,
      render: (_: unknown, record: AiErrorCluster) => (
        <a onClick={() => handleAnalyze(record)}>归因</a>
      ),
    },
  ];

  return (
    <div className="ai-workbench-page">
      <Row gutter={12}>
        <Col xs={24} xl={8}>
          <Card bordered={false} title="日志来源">
            <Radio.Group
              value={source}
              onChange={(e) => setSource(e.target.value)}
              style={{ marginBottom: 12 }}
            >
              <Radio.Button value="text">粘贴文本</Radio.Button>
              <Radio.Button value="file">上传文件</Radio.Button>
              <Radio.Button value="platform">平台日志</Radio.Button>
            </Radio.Group>

            {source === 'text' ? (
              <Input.TextArea
                rows={14}
                placeholder="把日志粘贴到这里"
                value={text}
                onChange={(e) => setText(e.target.value)}
                style={{ fontFamily: 'monospace' }}
              />
            ) : null}

            {source === 'file' ? (
              <Upload
                accept=".log,.txt"
                showUploadList={false}
                beforeUpload={async () => {
                  // 日志文件走对象存储 —— 这里只登记 id, 由后端按 view_url 取
                  message.info('请先在「对象存储」里上传日志文件, 然后把文件 id 填在下面');
                  return false;
                }}
              >
                <Button block icon={<InboxOutlined />}>
                  选择日志文件
                </Button>
              </Upload>
            ) : null}

            {source === 'file' ? (
              <Input
                style={{ marginTop: 12 }}
                placeholder="OSS 文件 id"
                value={fileId}
                onChange={(e) => setFileId(Number(e.target.value) || undefined)}
              />
            ) : null}

            {source === 'platform' ? (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 12 }}
                message="平台自身运行日志仅管理员可见"
                description="它是服务端的运行日志, 可能包含内部路径与堆栈信息。"
              />
            ) : null}

            <Space.Compact style={{ width: '100%', marginTop: 12 }}>
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
              <Select
                style={{ flex: 1 }}
                placeholder="选择模型"
                value={modelId}
                disabled={!vendorId}
                options={modelOptions}
                onChange={setModelId}
              />
            </Space.Compact>

            <Button
              type="primary"
              block
              style={{ marginTop: 12 }}
              loading={generatingLog}
              onClick={handleCluster}
              disabled={source === 'text' && !text.trim()}
            >
              开始聚类(不调用模型)
            </Button>
            {error ? (
              <Alert type="error" showIcon style={{ marginTop: 12 }} message={error} />
            ) : null}
          </Card>

          {spikes.length > 0 ? (
            <Card bordered={false} title="异常突增时段">
              <Space direction="vertical" size={4}>
                {spikes.map((spike, index) => (
                  <Tag key={index} color="red">
                    {spike.start_at} ~ {spike.end_at} · {spike.count} 次(基线 {spike.baseline})
                  </Tag>
                ))}
              </Space>
            </Card>
          ) : null}
        </Col>

        <Col xs={24} xl={16}>
          <Spin spinning={generatingLog}>
            <Card
              bordered={false}
              title="错误簇"
              extra={
                <Text type="secondary">
                  共 {totalLines} 行
                  {truncated ? '(已截断)' : ''}
                </Text>
              }
            >
              <Table
                rowKey="fingerprint"
                size="small"
                columns={columns}
                dataSource={clusters}
                pagination={{ pageSize: 20, showTotal: (count) => `共 ${count} 个错误簇` }}
                locale={{
                  emptyText: (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="还没有聚类结果 —— 在左边选个来源点「开始聚类」"
                    />
                  ),
                }}
                expandable={{
                  expandedRowRender: (record: AiErrorCluster) => {
                    const result = attribution[record.fingerprint];
                    if (!result) {
                      return <Text type="secondary">点「归因」让模型解读这个错误簇</Text>;
                    }
                    return (
                      <div>
                        <Paragraph strong>{result.summary}</Paragraph>
                        {(result.root_causes || []).map((cause: any, index: number) => {
                          const lowTrust = (cause.evidence?.length || 0) === 0;
                          return (
                            <Card
                              key={index}
                              size="small"
                              style={{ marginBottom: 8, opacity: lowTrust ? 0.55 : 1 }}
                              title={
                                <Space>
                                  <Text strong>{cause.cause}</Text>
                                  {lowTrust ? <Tag color="warning">低可信 · 无原文依据</Tag> : null}
                                </Space>
                              }
                            >
                              {cause.evidence?.map((item: string) => (
                                <Paragraph key={item} style={{ marginBottom: 2 }}>
                                  <Text code>{item}</Text>
                                </Paragraph>
                              ))}
                            </Card>
                          );
                        })}
                        {(result.fix_suggestions || []).map((fix: any, index: number) => (
                          <Card key={index} size="small" style={{ marginBottom: 8 }}>
                            <Paragraph strong style={{ marginBottom: 2 }}>
                              {fix.title}
                            </Paragraph>
                            <Paragraph style={{ marginBottom: 0 }}>{fix.detail}</Paragraph>
                          </Card>
                        ))}
                      </div>
                    );
                  },
                }}
              />
            </Card>
          </Spin>
        </Col>
      </Row>
    </div>
  );
};

export default LogPage;
