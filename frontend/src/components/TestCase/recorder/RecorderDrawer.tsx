import {Button, Col, Drawer, Empty, Form, Input, notification, Row, Space, TreeSelect, Upload} from "antd";
// @ts-ignore
import {connect} from '@umijs/max';
// @ts-ignore
import NoRecord from "../../../assets/no_record.svg";
import React, {useEffect, useState} from "react";
import CONFIG from '@/consts/config';
import RequestInfoList from "./RequestInfoList";
import {CameraOutlined, FireOutlined, ImportOutlined} from "@ant-design/icons";

enum ImportType {
  har = 1
}

interface DirectoryProps {

}

interface RecorderProps {
  recordLists: [];
}

interface RecorderDrawerProps {
  visible: boolean;
  setVisible: Function;
  directory: Array<DirectoryProps>;
  loading?: any;
  recorder?: RecorderProps;
  dispatch?: Function;
}

const RecorderDrawer = ({visible, setVisible, directory, loading, recorder, dispatch}: RecorderDrawerProps) => {
  const [form] = Form.useForm()
  const {recordLists} = recorder;
  const [record, setRecord] = useState([]);
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);

  const rowSelection = {
    selectedRowKeys,
    onChange: keys => {
      setSelectedRowKeys(keys)
    }
  };
  useEffect(() => {
    dispatch({
      type: 'recorder/queryRecordStatus',
    })
    setRecord([])
    form.resetFields()
  }, [visible])

  const onLoadRecords = (): void => {
    if (recordLists.length === 0) {
      notification.info({
        message: "🤔未能获取到录制信息",
        description: <span>你可以去<a href="/#/apiTest/record">录制页面</a> 直接生成用例哦🎉~</span>
      })
      return;
    }
    setRecord(recordLists)
  }

  const onGenerateCase = async () => {
    const values = await form.validateFields();
    const res = await dispatch({
      type: 'recorder/generateCase',
      payload: {
        directory_id: values.directory_id,
        name: values.name,
        requests: selectedRowKeys.map(key => ({
          request_headers: JSON.parse(record[key].request_headers),
          response_headers: JSON.parse(record[key].response_headers),
          cookies: JSON.parse(record[key].cookies),
          request_cookies: JSON.parse(record[key].request_cookies),
          response_content: record[key].response_content,
          request_method: record[key].request_method,
          url: record[key].url,
          body: record[key].body,
          status_code: record[key].status_code,
        }))
      }
    })
    if (res) {
      notification.success({
        message: '🎉 用例生成成功，可以去对应目录查看哦~',
        placement: 'topLeft'
      })
      dispatch({
        type: 'testcase/save',
        payload: {
          currentDirectory: [values.directory_id],
        }
      })
      setVisible(false)
      // 重新获取case
    }
  }

  const onUpload = async fileData => {
    setSelectedRowKeys([])
    const res = await dispatch({
      type: 'recorder/import',
      payload: {
        file: fileData.file,
        import_type: ImportType.har,
      }
    })
    if (res.length > 0) {
      notification.success({
        message: `🎉 成功导入${res.length}条数据，快去挑选请求生成用例吧~`,
        placement: 'topLeft'
      })
      setRecord(res)
    }
  }

  return (
    <Drawer title="生成用例" onClose={() => setVisible()} open={visible} width={960} extra={
      <Button disabled={selectedRowKeys.length === 0} onClick={onGenerateCase}
              type="primary"><FireOutlined/> 生成用例</Button>
    }>
      <Form form={form} {...CONFIG.SUB_LAYOUT}>
        <Row gutter={8}>
          <Col span={12}>
            <Form.Item label="场景目录" name="directory_id" rules={[{required: true, message: '请选择场景目录'}]}>
              <TreeSelect placeholder="请选择场景目录" treeLine treeData={directory}/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="场景名称" name="name" rules={[{required: true, message: '请输入场景名称'}]}>
              <Input placeholder="请输入场景名称"/>
            </Form.Item>
          </Col>
        </Row>
      </Form>
      {
        record.length === 0 ?
          <Empty image={NoRecord} styles={{image: {height: 220}}} description="当前没有任何请求数据，你可以选择【录制】后的数据，也可以导入har文件提取接口👏">
            <Space>
              <Button onClick={onLoadRecords}><CameraOutlined/> 录制请求</Button>
              <Upload showUploadList={false} customRequest={onUpload} fileList={[]}>
                <Button type="primary">
                  <ImportOutlined/>
                  导入Har
                </Button>
              </Upload>
            </Space>
          </Empty> :
          <RequestInfoList dataSource={record} rowSelection={rowSelection} rowKey="index"
                           dispatch={dispatch}
                           loading={loading.effects['recorder/generateCase']}/>
      }
    </Drawer>
  )
}

export default connect(({recorder, loading}) => ({recorder, loading}))(RecorderDrawer);
