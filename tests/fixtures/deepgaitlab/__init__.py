"""Offline DeepGaitLab (GBLV2NPH) fixture.

Block texts are verbatim excerpts copied from the evidence archive of the user's first real run
(facts table 'context' column = raw MinerU text incl. LaTeX; judge context = cleaned sentences; judge quotes).
Where only a cleaned sentence was archived, the LaTeX form below is a faithful reconstruction of the same
characters (marked RECON). No numbers were invented: every number appears in the archive.
The full MinerU cache exists only on the user's Mac.
"""
from litreader.parse.blocks import Block


def B(o, kind, page, text="", **kw):
    return Block(kind=kind, physical_page=page, bbox_norm=None, text=text, order=o, **kw)


BLOCKS = [
    B(1, "title", 1, "DeepGaitLab：由合成数据驱动的准确灵活无标记运动追踪"),
    B(2, "text", 1, "Soyong Shin, Sijia Li, Zhixiong Li, Eni Halilaj"),          # author line (archive: rejected meta.authors)
    B(41, "text", 4, "我们在两种不同环境中采集了 80 名个体的数据"),
    B(70, "title", 10, "结果"),
    B(75, "text", 10, "在该数据集中，23 名无任何步态障碍的参与者完成了地面行走和八项物理治疗练习，同时使用基于标记和无标记系统进行记录（图 2A）。"),
    # RECON: archive keeps the fact context with LaTeX and the cleaned sentence with "p < 0.0001 AA"
    B(78, "text", 11, "在双相机设置下，DeepGaitLab 优于 OpenCap，其在所有任务和下肢自由度上相对于基于标记点分析的均方根差（RMSD）显著更低 "
                      "$( 4 . 2 \\pm 0 . 6 ^ { \\circ } \\mathrm { { V S . 5 . 9 \\pm 1 . 3 ^ { \\circ } } }$ $p < 0 . 0 0 0 1$ AA ）（图 2C）。"),
    B(79, "text", 11, "相比之下，随着相机数量从两台逐渐增加到十台，DeepGaitLab 的 RMSD 显著降低（两台时为 4.2±0.6° ，六台时为 3.8±0.5° p < 0.0001；"
                      "OpenCap 两台时为 5.9±1.3°，十台时为 $5 . 9 \\pm 1 . 0 $ $p = 0 . 7 0 2 0 )$"),
    B(89, "text", 13, "ACLR 参与者在髋屈/伸 $\\mathrm { ( O p e n C a p ~ 1 3 . 4 \\pm 7 . 9 ^ { \\circ } ~ v s . ~ 7 . 3 \\pm 4 . 3 ^ { \\circ } , } p = 0 . 0 0 0 1$ "
                      "$\\mathrm { T h e i a 3 D 9 . 8 \\pm 3 . 9 ^ { \\circ } v s . 7 . 2 \\pm 2 . 6 ^ { \\circ } , ~ } p = 0 . 0 2 1 7 )$ 的误差高于无活动受限者。"
                      "DeepGaitLab 在两组中保持稳定性能，在双相机 $\\left( \\boldsymbol { p } = 0 . 1 2 0 8 \\right)$ 或十相机 $( p = 0 . 3 1 5 1 )$ 设置下，"
                      "ACLR 患者与无活动受限者之间均无显著差异。"),
    B(92, "text", 14, "基于标记点的运动捕捉识别出显著的髋关节屈曲/伸展峰值不对称（ $( 5 . 9 \\pm 1 1 . 7 ^ { \\circ }$ ， $p =$ 0.0032 ），"
                      "OpenCap 成功检测到该不对称 $( 1 0 . 0 \\pm 1 4 . 9 ^ { \\circ } , p = 0 . 0 0 0 3 )$，而 Theia3D 未检测到（ $( 3 . 2 \\pm 1 0 . 6 ^ { \\circ }$ ， $p = 0 . 0 6 6 1 \\ \\cdot$ ）。"),
    B(104, "text", 16, "在双相机配置下，DeepGaitLab 在与基于标记的动作捕捉的不对称性一致性方面优于 OpenCap，实现了显著更低的 RMSD（4.32 ± 1.27% vs. 6.83 ± 1.57%， \ufffd <0.0001）"
                       "和更高的组内相关系数 $( \\mathrm { I C C } ; ~ 0 . 9 1 \\pm 0 . 0 4 \\mathrm { v s . } 0 . 8 3 \\pm 0 . 0 9 , ~ p < 0 . 0 0 0 1 )$。"),
    B(109, "text", 17, "图 4. MCI 与卒中人群的步长不对称。(B) 在双摄像头配置下，DeepGaitLab 在步长不对称性上与基于标记分析的一致性高于 OpenCap；仅使用两个摄像头，"
                       "其性能即可与 Theia3D 的八摄像头配置相当。(C) DeepGaitLab 与基于标记分析的相关性高于 OpenCap，并在摄像头数量显著更少的情况下，与Theia3D 具有相当的相关性。"),
    B(111, "text", 17, "使用两台相机时（图 5A），DeepGaitLab 基于标记的逆动力学得到的 rRMSD 低于 OpenCap（ $\\phantom { - } 0 . 2 7 \\pm 0 . 0 7$ 对 $0 . 4 2 \\pm 0 . 1 7$ p<0.0001）。"
                       "当使用在更密集的相机配置下，DeepGaitLab 与 Theia3D 的性能相当（图 5B），但在行走中则不然（两台相机的 DeepGaitLab 为 0.22±0.03，十台相机的 Theia3D 为 0.16±0.03, p<0.0001）。"),
    B(133, "text", 21, "最大增益见于膝关节屈/伸 $( 3 . 0 \\pm 0 . 7 ^ { \\circ } \\mathrm { { v s . 3 . 6 \\pm 0 . 6 ^ { \\circ } , } } p = 0 . 0 0 0 4 )$"),
    B(174, "figure", 29, "", caption="图 8. 密集标志点检测网络架构。(A) 我们使用视频分割模型 SAMURAI <sup>[47]</sup> 从 RGB 图像中提取分割掩码。",
      img_path="images/f8.jpg"),
    B(213, "text", 36, "在获得匹兹堡大学机构审查委员会批准（STUDY19060017）并取得知情同意后，我们招募了19名参与者，其中包括8名轻度认知障碍者（4名女性、4名男性；"
                       "11名卒中者（4名女性、7名男性"),
]
FIG5_CAPTION = ("图 5. 无行动能力限制人群的逆动力学性能。(A) 在双相机配置下，DeepGaitLab 优于 OpenCap，尤其在单腿深蹲和非矢状面自由度中。"
                "(B) 在十相机设置下，DeepGaitLab 与 Theia3D 在各活动和自由度上的表现相似。")
