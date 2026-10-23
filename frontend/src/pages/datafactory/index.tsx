import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Col, InputNumber, Modal, Row, Space, Tooltip, message } from 'antd';
import { ExperimentOutlined, PlayCircleOutlined } from '@ant-design/icons';
import { useModel } from '@umijs/max';
import { listEnvironment, listDbConfig } from '@/services/configure';
import { listProject } from '@/services/project';
import { listTestCaseTree } from '@/services/testcase';
import { DataFactoryColumn, DataFactoryDataset, TableColumn } from '@/services/datafactory';
import DatasetList from './DatasetList';
import DatasetForm, { parseColumns } from './DatasetForm';
import GenerateModal from './GenerateModal';
import AiParseModal from './AiParseModal';
import TableColumnPicker, { guessType } from './TableColumnPicker';
import './index.less';

interface Option {
  label: string;
  value: number;
}

/**
 * 数据工厂
 *
 * 数据集(字段规则) -> 批量生成 -> 导出 / 写库 / 绑定用例
 */
const DataFactory: React.FC = () => {
  const {
    datasets,
    current,
    setCurrent,
    rows,
    tables,
    loading,
    saving,
    generating,
    exporting,
    writing,
    binding,
    fetchDatasets,
    saveDataset,
    removeDataset,
    generate,
    exportFile,
    writeDb,
    bindCase,
    loadTables,
    loadTableColumns,
  } = useModel('datafactory');

  const [keyword, setKeyword] = useState('');
  const [envOptions, setEnvOptions] = useState<Option[]>([]);
  const [projectOptions, setProjectOptions] = useState<Option[]>([]);
  const [databaseOptions, setDatabaseOptions] = useState<Option[]>([]);
  const [caseOptions, setCaseOptions] = useState<Option[]>([]);
  const [genCount, setGenCount] = useState<number>(10);
  const [genSeed, setGenSeed] = useState<number | undefined>(42);
  const [genOpen, setGenOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  // 导入弹窗里选中的目标库(独立于表单, 让弹窗自成闭环)
  const [pickerDatabaseId, setPickerDatabaseId] = useState<number | undefined>();
  // 新建态: 此时 current 为空, 但不能被"自动选中第一个"覆盖
  const [creating, setCreating] = useState(false);

  // 加载环境 / 项目 / 数据库配置 / 用例列表
  useEffect(() => {
    listEnvironment({ page: 1, size: 100 })
      .then((res: any) => {
        if (res?.code === 0) {
          setEnvOptions((res.data || []).map((e: any) => ({ label: e.name, value: e.id })));
        }
      })
      .catch(() => undefined);
    listProject({ page: 1, size: 100 })
      .then((res: any) => {
        if (res?.code === 0) {
          setProjectOptions((res.data || []).map((p: any) => ({ label: p.name, value: p.id })));
        }
      })
      .catch(() => undefined);
    listDbConfig({})
      .then((res: any) => {
        if (res?.code === 0) {
          setDatabaseOptions((res.data || []).map((d: any) => ({ label: d.name, value: d.id })));
        }
      })
      .catch(() => undefined);
    listTestCaseTree({})
      .then((res: any) => {
        if (res?.code === 0) {
          setCaseOptions((res.data || []).map((c: any) => ({ label: c.name, value: c.id })));
        }
      })
      .catch(() => undefined);
  }, []);

  // 首次进入拉取数据集列表。之前漏了这一步, 页面刚打开时左侧永远是"还没有数据集",
  // 只有触发过保存/搜索才会拉数据
  useEffect(() => {
    fetchDatasets({});
  }, [fetchDatasets]);

  // 默认选中第一个数据集(新建态除外)
  useEffect(() => {
    if (!creating && !current && datasets.length > 0) {
      setCurrent(datasets[0]);
    }
  }, [datasets, current, creating, setCurrent]);

  const currentColumns = useMemo<DataFactoryColumn[]>(
    () => (current ? parseColumns(current.columns) : []),
    [current]
  );

  const onSearch = useCallback(
    (value: string) => {
      setKeyword(value);
      fetchDatasets({ name: value });
    },
    [fetchDatasets]
  );

  const onSave = async (payload: Record<string, unknown>) => {
    const saved = await saveDataset(payload);
    // 成功提示由 saveDataset 内的 auth.response(res, true) 统一弹, 这里不再重复 message
    if (!saved) return;
    // 新建: 切到编辑态并选中, 否则一直停在"新建态", 紧接着点「生成预览」会被拦
    // 编辑: 同样要把落库结果同步回 current —— 「从表结构导入」/「生成预览」读的都是
    // current.database_id, 不同步的话刚选的目标库要重新点一次数据集才生效
    setCreating(false);
    setCurrent(saved);
  };

  const onRemove = (id: number) => {
    Modal.confirm({
      title: '确定删除这个数据集吗?',
      content: '删除后不会影响已经绑定到用例的测试数据',
      onOk: async () => {
        await removeDataset(id);
      },
    });
  };

  const onDuplicate = (dataset: DataFactoryDataset) => {
    setCreating(true);
    setCurrent({
      ...dataset,
      id: 0,
      name: `${dataset.name} 副本`,
    } as DataFactoryDataset);
    message.info('已载入为新数据集, 改个名字保存即可');
  };

  const onGenerate = async () => {
    if (!current) {
      message.info('请先选择或新建一个数据集');
      return;
    }
    const data = await generate({
      dataset_id: current.id,
      count: genCount,
      seed: genSeed,
    });
    if (data) {
      setGenOpen(true);
    }
  };

  /**
   * 保存数据集时的通用载荷: 以 current 为底, 调用方只覆盖自己要改的字段。
   * 这样「AI 应用规则」「从表结构导入」都不会把用户在表单里还没保存的编辑一起写库。
   */
  const buildPayload = (
    base: DataFactoryDataset,
    overrides: Record<string, unknown> = {}
  ): Record<string, unknown> => ({
    id: base.id,
    name: base.name,
    env: base.env,
    project_id: base.project_id,
    database_id: base.database_id,
    table_name: base.table_name,
    columns: base.columns,
    count: base.count,
    seed: base.seed,
    remark: base.remark,
    status: base.status,
    ...overrides,
  });

  const onAiConfirm = async (newColumns: DataFactoryColumn[], count: number) => {
    setAiOpen(false);
    if (!current) {
      message.info('请先选择或新建一个数据集');
      return;
    }
    await onSave(buildPayload(current, { columns: JSON.stringify({ columns: newColumns }), count }));
  };

  const onOpenPicker = async () => {
    if (!current) {
      message.info('请先选择或新建一个数据集');
      return;
    }
    // 打开时用数据集里已配的目标库做初值, 没配也能在弹窗里现选。
    // 表列表由 loadTables 按库刷新; 没选库时弹窗会禁用表下拉, 不需要手动清空。
    setPickerDatabaseId(current.database_id);
    setPickerOpen(true);
    if (current.database_id) await loadTables(current.database_id);
  };

  const onPickDatabase = async (id?: number) => {
    setPickerDatabaseId(id);
    if (id) await loadTables(id);
  };

  const onPickTable = async (table: string): Promise<TableColumn[]> => {
    if (!pickerDatabaseId) return [];
    return loadTableColumns(pickerDatabaseId, table);
  };

  const onImportColumns = async (columns: any[], databaseId?: number, table?: string) => {
    setPickerOpen(false);
    if (!current) return;
    const rules: DataFactoryColumn[] = columns.map((c) => ({
      name: c.name,
      type: guessType(c.type),
      rule: c.primary_key
        ? { kind: 'sequence', start: 1, step: 1 }
        : { kind: 'fixed', value: '' },
      unique: false,
      nullable: c.nullable,
      default: c.default ?? null,
      comment: c.primary_key ? '主键' : '',
    }));
    // 库 / 表 / 字段一并写回数据集, 下次点生成预览或写库时就不用再填一遍
    await onSave(
      buildPayload(current, {
        columns: JSON.stringify({ columns: rules }),
        database_id: databaseId ?? current.database_id,
        table_name: table ?? current.table_name,
      })
    );
  };

  return (
    <div className="df-page">
      <Row gutter={12}>
        <Col span={6}>
          <Card bordered={false} styles={{ body: { padding: 12 } }}>
            <DatasetList
              datasets={datasets}
              current={current}
              loading={loading}
              keyword={keyword}
              onKeywordChange={onSearch}
              onSelect={(item) => {
                setCreating(false);
                setCurrent(item);
              }}
              onCreate={() => {
                setCreating(true);
                setCurrent(null);
              }}
              onRemove={onRemove}
              onDuplicate={onDuplicate}
            />
          </Card>
        </Col>
        <Col span={18}>
          <Card bordered={false} styles={{ body: { padding: 12 } }}>
            <DatasetForm
              dataset={creating ? null : current}
              saving={saving}
              envOptions={envOptions}
              projectOptions={projectOptions}
              databaseOptions={databaseOptions}
              onSave={onSave}
              onAiParse={() => setAiOpen(true)}
              onImportFromTable={onOpenPicker}
            />
            <Row justify="end" style={{ marginTop: 12 }}>
              <Space>
                <span>生成条数</span>
                <InputNumber
                  style={{ width: 100 }}
                  min={1}
                  max={10000}
                  value={genCount}
                  onChange={(v) => setGenCount(v || 1)}
                />
                <Tooltip title="相同种子生成的数据完全一致, 留空表示每次随机">
                  <span>随机种子</span>
                </Tooltip>
                <InputNumber
                  style={{ width: 110 }}
                  min={0}
                  placeholder="随机"
                  value={genSeed}
                  onChange={(v) => setGenSeed(v === null ? undefined : v)}
                />
                <Button type="primary" icon={<PlayCircleOutlined />} loading={generating} onClick={onGenerate}>
                  生成预览
                </Button>
              </Space>
            </Row>
            <Alert
              style={{ marginTop: 12 }}
              type="info"
              showIcon
              icon={<ExperimentOutlined />}
              message="数据落地后, 用「绑定到用例」写入用例的测试数据, 用例里用 ${字段名} 引用即可自动跑数据驱动"
            />
          </Card>
        </Col>
      </Row>

      <GenerateModal
        open={genOpen}
        rows={rows}
        columns={currentColumns}
        defaultDatabaseId={current?.database_id}
        defaultTableName={current?.table_name}
        defaultEnv={current?.env}
        exporting={exporting}
        writing={writing}
        binding={binding}
        databaseOptions={databaseOptions}
        caseOptions={caseOptions}
        onCancel={() => setGenOpen(false)}
        onExport={(payload, filename) => exportFile(payload, filename)}
        onWriteDb={async (payload) => {
          const ok = await writeDb(payload);
          if (ok) setGenOpen(false);
        }}
        onBindCase={async (payload) => {
          const ok = await bindCase(payload);
          if (ok) setGenOpen(false);
        }}
      />

      <AiParseModal open={aiOpen} onCancel={() => setAiOpen(false)} onConfirm={onAiConfirm} />

      <TableColumnPicker
        open={pickerOpen}
        databaseOptions={databaseOptions}
        databaseId={pickerDatabaseId}
        tables={tables}
        onCancel={() => setPickerOpen(false)}
        onConfirm={onImportColumns}
        onDatabaseChange={onPickDatabase}
        onTableChange={onPickTable}
      />
    </div>
  );
};

export default DataFactory;
