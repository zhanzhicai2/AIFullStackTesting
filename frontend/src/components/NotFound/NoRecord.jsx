import {Empty} from "antd";
import noRecord from '@/assets/no_record.svg';

export default ({desc, height = 180, image = noRecord}) => {
  return <Empty
    image={image}
    styles={{
      image: {
        height,
      },
    }}
    description={desc || '暂无数据'}
  >
  </Empty>
}
