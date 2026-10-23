// 录制/导入 har 得到的单条请求信息。
// 字段与后端 app/schema/request.py 的 RequestInfo 保持一致,
// 区别是前端会把 headers/cookies 序列化成 JSON 字符串后再交给表格展示。
export interface RequestInfo {
  /** 前端补的行号,也是表格的 rowKey */
  index: number;
  url: string;
  body: string;
  request_method: string;
  /** JSON 字符串 */
  request_headers: string;
  /** JSON 字符串 */
  response_headers: string;
  /** JSON 字符串 */
  cookies: string;
  /** JSON 字符串 */
  request_cookies: string;
  response_content: string;
  status_code: number;
}
