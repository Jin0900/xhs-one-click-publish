"""xhs_3x4 确定性渲染器：模板 JSON + 内容 JSON -> 1080x1440 PNG。

分层（参考 satori 管线思想，全部自行实现）：
  model        模板/数据加载与结构校验
  text_layout  字体注册/fallback、CJK 换行/避头尾、测量
  assets       AI 素材 fit/anchor/旋转/alpha 包围盒/scrim
  engine_pillow 按 slot 确定性绘制
  validate     V1-V9 发布前门禁
"""
