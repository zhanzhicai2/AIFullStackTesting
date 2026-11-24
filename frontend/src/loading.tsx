import { PageLoading } from "@ant-design/pro-components"
import { Loading } from "@icon-park/react"
import "@icon-park/react/styles/index.css"

export default () => {
    // 不传 `tip`: pro-layout 的 PageLoading 会把 tip 原样透传给内部 <Spin />, 而那个 Spin
    // 没有 children —— antd 判定「非 nest 也非 fullscreen」会报
    // `[antd: Spin] tip only work in nest or fullscreen pattern`。
    // 而 antd 在非 nest 模式下**根本不渲染 tip**, 文字本来就显示不出来, 只贡献一条警告。
    // 想显示文字就改用 antd 原生 `<Spin fullscreen tip="..." />`(全屏遮罩, 行为不同)。
    return <PageLoading indicator={<Loading spin={true} theme="outline" size="36" fill="#4a90e2" strokeLinecap="butt" />} />
}