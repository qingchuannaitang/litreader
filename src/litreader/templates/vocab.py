"""Controlled vocabularies for templates (design §2.3, §5.2; spec §5.2 role enum)."""

FORMAT_VERSION = 1

ROLES = {"main": "MAIN_NOTE", "module": "MODULE", "overview": "OVERVIEW", "evidence": "EVIDENCE_APPENDIX"}
ROLE_ZH = {"MAIN_NOTE": "主模板", "MODULE": "专业模块", "OVERVIEW": "总览", "EVIDENCE_APPENDIX": "证据附录"}

STUDY_TYPES = {
    "rct": "随机对照试验", "non_randomized_intervention": "非随机干预研究", "cohort": "队列研究",
    "case_control": "病例对照研究", "cross_sectional": "横断面研究", "diagnostic_accuracy": "诊断准确性研究",
    "prediction_model": "预测/诊断模型开发与验证", "systematic_review": "系统综述/Meta 分析",
    "narrative_review": "叙述性综述", "methods_technical": "方法学/技术/AI 研究", "qualitative": "质性研究",
    "case_report": "病例报告", "other": "其他",
}
ANY = "any"
LEVELS = ("L1", "L2", "L3")

HEADER_BLOCKS = ("info_callout", "nav", "three_minute", "one_liner", "pdf_nav", "reading_convention")
SECTION_BLOCKS = ("paragraphs", "supports", "tables", "negative_results", "figures", "author_conclusion", "evaluation",
                  "review_items", "borrow_items", "next_checks", "protected_zone", "unknown_top", "evidence_nav",
                  "module_fields", "module_slot", "project_lens")
# data keys produced by the writer schema (schema_v2); other section ids become "extra" sections
DATA_KEYS = ("s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10")
SUFFIX_MODES = ("none", "colon", "append")

# blocks the code always renders even if a template omits them (design §7)
MANDATORY_HEADER = HEADER_BLOCKS   # spec §3.2 fixed first layer: a template may reorder, not drop
MANDATORY_SECTION = ("unknown_top", "protected_zone", "evidence_nav")

FEATURES = {"PDF_PAGE_LINK": None, "ORIGINAL_FIGURE": "figures", "PROJECT_LENS": "borrow_items"}
