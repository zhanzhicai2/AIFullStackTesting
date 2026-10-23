import { Modal, Tabs, Typography } from "antd";
import Table, { ColumnsType } from "antd/es/table";


interface VariableModalProps {
    open?: boolean;
    onCancel: (e: React.MouseEvent<HTMLButtonElement, MouseEvent>) => void;
    gconfig: GConfigDataType[];
    variables: StepDataType[];
}

interface GConfigDataType {
    name: string;
}

interface StepDataType extends GConfigDataType {
    stepName: string;
}




const { TabPane } = Tabs;

// 变量名列在全局变量/用例变量两张表里复用,抽成泛型以便两侧的
// ColumnType 各自绑定到自己的行类型上
const buildNameColumns = <T extends GConfigDataType>(): ColumnsType<T> => [
    {
        title: '变量名',
        dataIndex: "name",
        key: 'name',
        render: (name) => <Typography.Text copyable>{name}</Typography.Text>
    },
]

const VariableModal: React.FC<VariableModalProps> = ({ open, gconfig, variables, onCancel }) => {

    const columns: ColumnsType<GConfigDataType> = buildNameColumns<GConfigDataType>()

    const stepColumns: ColumnsType<StepDataType> = [
        ...buildNameColumns<StepDataType>(),
        {
            title: '来源',
            dataIndex: "stepName",
            key: 'stepName',
        },
    ]

    return (
        <Modal title="变量列表" open={open} width={500} footer={null} onCancel={onCancel}>
            <Tabs>
                <TabPane key="global" tab="全局变量">
                    <Table columns={columns} dataSource={gconfig} size="small" />
                </TabPane>
                <TabPane key="case" tab="用例变量">
                    <Table columns={stepColumns} dataSource={variables} size="small" />
                </TabPane>
            </Tabs>
        </Modal>
    )
}


export default VariableModal;