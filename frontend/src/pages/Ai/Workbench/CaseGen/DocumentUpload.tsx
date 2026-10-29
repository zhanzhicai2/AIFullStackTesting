import React, { useState } from 'react';
import { Alert, Space, Typography, Upload, message } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import { parseAiDocument } from '@/services/aiWorkbench';

const { Text } = Typography;

/** 支持的文档类型 —— 与后端 app/utils/document_parser.py 的白名单一致 */
export const SUPPORTED_EXTENSIONS = ['.pdf', '.docx', '.md', '.markdown', '.txt'];
/** 单文件大小上限 —— 与后端一致(20MB) */
export const MAX_FILE_SIZE = 20 * 1024 * 1024;

export interface DocumentUploadProps {
  /** 解析成功后把正文交给父组件 */
  onParsed: (content: string, filename: string, warnings: string[]) => void;
  /** 解析失败时把原因交给父组件(G5 的可操作原因) */
  onError?: (reason: string) => void;
  disabled?: boolean;
}

/**
 * 需求文档上传
 *
 * **G3** —— 未配置对象存储时: 文档**只本次解析不落盘**, 不阻断上传。
 * (平台的对象存储是可选的, 解析出来的正文直接进 prompt, 不需要落盘。)
 */
const DocumentUpload: React.FC<DocumentUploadProps> = ({ onParsed, onError, disabled }) => {
  const [parsing, setParsing] = useState(false);
  const [fileName, setFileName] = useState<string>('');
  const [warnings, setWarnings] = useState<string[]>([]);

  const handleFile = async (file: File) => {
    const lower = file.name.toLowerCase();
    const ok = SUPPORTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
    if (!ok) {
      const reason = '不支持的文件类型, 当前支持 PDF / Word(.docx) / Markdown / 纯文本';
      message.error(reason);
      onError?.(reason);
      return false;
    }
    if (file.size > MAX_FILE_SIZE) {
      const reason = '文件超过 20MB 上限';
      message.error(reason);
      onError?.(reason);
      return false;
    }
    setParsing(true);
    setFileName(file.name);
    try {
      // 真正的解析在后端 —— 前端只做类型与大小预校验
      const res: any = await parseAiDocument(file);
      if (res?.code !== 0) {
        const reason = res?.msg || '文档解析失败, 请改用文本输入';
        message.error(reason);
        onError?.(reason);
        setWarnings([]);
        return false;
      }
      const data = res.data || {};
      setWarnings(data.warnings || []);
      if (!data.content) {
        const reason = '未能提取到正文, 建议改用文本输入';
        message.warning(reason);
        onError?.(reason);
        return false;
      }
      onParsed(data.content, file.name, data.warnings || []);
      message.success(`解析成功, 共 ${data.chars} 个字符`);
      return true;
    } catch (e: any) {
      const reason = e?.message || '文档解析失败, 请改用文本输入';
      message.error(reason);
      onError?.(reason);
      return false;
    } finally {
      setParsing(false);
    }
  };

  return (
    <div>
      <Upload.Dragger
        accept={SUPPORTED_EXTENSIONS.join(',')}
        beforeUpload={handleFile}
        showUploadList={false}
        multiple={false}
        disabled={disabled || parsing}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">点击或拖拽需求文档到此处</p>
        <p className="ant-upload-hint">
          支持 PDF / Word(.docx) / Markdown / 纯文本, 单个文件不超过 20MB
        </p>
      </Upload.Dragger>

      {/* **G3** —— 未配置对象存储时的降级说明(不阻断) */}
      <Alert
        type="info"
        showIcon
        style={{ marginTop: 12 }}
        message="未配置对象存储, 文档将仅本次解析不落盘"
        description="解析出的正文直接进入本次生成, 不会保存到对象存储。"
      />

      {fileName ? (
        <Space style={{ marginTop: 8 }} size={4}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            已解析: {fileName}
          </Text>
        </Space>
      ) : null}

      {warnings.length > 0 ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 8 }}
          message="解析告警"
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {warnings.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          }
        />
      ) : null}
    </div>
  );
};

export default DocumentUpload;
