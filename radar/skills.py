"""Skill dictionary and text helpers for the skills radar.

Each skill has a category and a regular expression. A skill counts once per
posting (document frequency), so a posting that says "Python" ten times still
counts as one posting that mentions Python.
"""
import html
import re

# name: (category, pattern, case_sensitive)
_RAW = {
    # languages
    "Python": ("language", r"\bpython\b", False),
    "Java": ("language", r"\bjava\b(?!\s*script)", False),
    "JavaScript": ("language", r"\bjavascript\b|\bnode\.?js\b", False),
    "TypeScript": ("language", r"\btypescript\b", False),
    "C++": ("language", r"c\+\+", False),
    "C": ("language", r"(?<![\w+#.])C(?![\w+#.])", True),
    "Go": ("language", r"\bgolang\b|\bGo\b(?=\s*(?:,|/|\(|language|lang\b|programming))", True),
    "Rust": ("language", r"\brust\b", False),
    "Kotlin": ("language", r"\bkotlin\b", False),
    "SQL": ("language", r"\bsql\b", False),
    "Bash/Shell": ("language", r"\bbash\b|\bshell script", False),
    # frontend
    "React": ("frontend", r"\breact(?:\.?js)?\b", False),
    "Next.js": ("frontend", r"\bnext\.?js\b", False),
    "Angular": ("frontend", r"\bangular\b", False),
    "Vue": ("frontend", r"\bvue(?:\.?js)?\b", False),
    "HTML/CSS": ("frontend", r"\bhtml5?\b|\bcss3?\b", False),
    # backend and systems
    "Node.js": ("backend", r"\bnode\.?js\b", False),
    "Django": ("backend", r"\bdjango\b", False),
    "Flask": ("backend", r"\bflask\b", False),
    "FastAPI": ("backend", r"\bfastapi\b", False),
    "Spring": ("backend", r"\bspring\s?boot\b|\bspring framework\b", False),
    "REST APIs": ("backend", r"\brest(?:ful)?\s+api|\brest\b(?=\s*(?:,|/|and))", False),
    "GraphQL": ("backend", r"\bgraphql\b", False),
    "gRPC": ("backend", r"\bgrpc\b", False),
    "Microservices": ("backend", r"\bmicro-?services?\b", False),
    "System design": ("backend", r"\bsystem design\b|\bdesign (?:large|scalable|distributed) systems\b", False),
    "Scalable systems": ("backend", r"\bscalab(?:le|ility)\b|\bhigh[- ]availability\b|\blow[- ]latency\b", False),
    "Distributed systems": ("backend", r"\bdistributed (?:systems?|computing)\b", False),
    # data stores
    "PostgreSQL": ("data", r"\bpostgres(?:ql)?\b", False),
    "MySQL": ("data", r"\bmysql\b", False),
    "MongoDB": ("data", r"\bmongo(?:db)?\b", False),
    "Redis": ("data", r"\bredis\b", False),
    "Kafka": ("data", r"\bkafka\b", False),
    "Spark": ("data", r"\bapache spark\b|\bpyspark\b|\bspark\b(?=\s*(?:,|/|and|streaming|sql))", False),
    "Elasticsearch": ("data", r"\belastic\s?search\b|\bopensearch\b", False),
    "Airflow": ("data", r"\bairflow\b", False),
    "Pandas/NumPy": ("data", r"\bpandas\b|\bnumpy\b", False),
    # cloud and devops
    "AWS": ("cloud", r"\baws\b|\bamazon web services\b", False),
    "GCP": ("cloud", r"\bgcp\b|\bgoogle cloud\b", False),
    "Azure": ("cloud", r"\bazure\b", False),
    "Docker": ("cloud", r"\bdocker\b", False),
    "Kubernetes": ("cloud", r"\bkubernetes\b|\bk8s\b", False),
    "Terraform": ("cloud", r"\bterraform\b", False),
    "CI/CD": ("cloud", r"\bci/cd\b|\bcontinuous (?:integration|delivery|deployment)\b", False),
    "Linux": ("cloud", r"\blinux\b|\bunix\b", False),
    "Git": ("cloud", r"\bgit\b(?!hub actions)|\bgithub\b", False),
    # machine learning and AI
    "Machine learning": ("ml_ai", r"\bmachine learning\b|\bml\b", False),
    "Deep learning": ("ml_ai", r"\bdeep learning\b", False),
    "PyTorch": ("ml_ai", r"\bpytorch\b", False),
    "TensorFlow": ("ml_ai", r"\btensorflow\b|\bkeras\b", False),
    "scikit-learn": ("ml_ai", r"\bscikit-?learn\b|\bsklearn\b", False),
    "LLMs": ("ml_ai", r"\bllms?\b|\blarge language models?\b|\bgenerative ai\b|\bgenai\b|\bgen ai\b", False),
    "RAG": ("ml_ai", r"\brag\b|\bretrieval[- ]augmented\b", False),
    "Agents": ("ml_ai", r"\bai agents?\b|\bagentic\b|\bmulti-agent\b|\bllm agents?\b", False),
    "LangChain/LangGraph": ("ml_ai", r"\blangchain\b|\blanggraph\b|\bllamaindex\b", False),
    "Vector databases": ("ml_ai", r"\bvector (?:database|db|store|search)s?\b|\bembeddings?\b|\bfaiss\b|\bpinecone\b", False),
    "NLP": ("ml_ai", r"\bnlp\b|\bnatural language processing\b", False),
    "Computer vision": ("ml_ai", r"\bcomputer vision\b|\bopencv\b|\bimage processing\b|\byolo", False),
    "MLOps": ("ml_ai", r"\bmlops\b|\bmlflow\b|\bmodel (?:deployment|serving)\b", False),
    "Reinforcement learning": ("ml_ai", r"\breinforcement learning\b", False),
    "Fine-tuning": ("ml_ai", r"\bfine-?tuning\b|\blora\b|\brlhf\b", False),
    "Hugging Face": ("ml_ai", r"\bhugging ?face\b|\btransformers\b", False),
    "Evaluation/metrics": ("ml_ai", r"\bevals?\b|\bevaluation (?:framework|metrics?|pipeline)s?\b|\bbenchmark", False),
    "XGBoost": ("ml_ai", r"\bxgboost\b|\bgradient boosting\b", False),
    # robotics and embedded
    "ROS": ("robotics_embedded", r"\bros2?\b(?!\w)|\brobot operating system\b", False),
    "Robotics": ("robotics_embedded", r"\brobot(?:ics|s)?\b", False),
    "Embedded systems": ("robotics_embedded", r"\bembedded\b", False),
    "Firmware": ("robotics_embedded", r"\bfirmware\b", False),
    "RTOS": ("robotics_embedded", r"\brtos\b|\bfreertos\b", False),
    "Microcontrollers": ("robotics_embedded", r"\bmicrocontrollers?\b|\barduino\b|\bstm32\b|\besp32\b|\braspberry pi\b", False),
    "SLAM/Navigation": ("robotics_embedded", r"\bslam\b|\bnavigation stack\b|\bpath planning\b|\bmotion planning\b", False),
    "Sensor fusion": ("robotics_embedded", r"\bsensor fusion\b|\bkalman\b|\blidar\b|\bimu\b", False),
    "Control systems": ("robotics_embedded", r"\bcontrol (?:systems?|theory|algorithms?)\b|\bpid\b", False),
    "FPGA/Verilog": ("robotics_embedded", r"\bfpga\b|\bverilog\b|\bvhdl\b|\brtl\b", False),
    "MATLAB/Simulink": ("robotics_embedded", r"\bmatlab\b|\bsimulink\b", False),
    # fundamentals and practice
    "Data structures": ("fundamentals", r"\bdata structures?\b", False),
    "Algorithms": ("fundamentals", r"\balgorithms?\b", False),
    "OOP": ("fundamentals", r"\bobject[- ]oriented\b|\boop\b", False),
    "Operating systems": ("fundamentals", r"\boperating systems?\b", False),
    "Networking": ("fundamentals", r"\bcomputer networks?\b|\btcp/ip\b|\bnetworking\b", False),
    "Testing": ("practice", r"\bunit tests?\b|\btest[- ]driven\b|\btdd\b|\bautomated tests?\b|\btesting\b|\bpytest\b", False),
    "Agile/Scrum": ("practice", r"\bagile\b|\bscrum\b", False),
    "Open source": ("practice", r"\bopen[- ]source\b", False),
}

SKILLS = {
    name: (cat, re.compile(pat, 0 if cs else re.IGNORECASE))
    for name, (cat, pat, cs) in _RAW.items()
}

# What Ashritha's resumes show today (both PDFs, 2026-11-13).
ON_RESUME = {
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C", "React", "Next.js",
    "HTML/CSS", "Node.js", "FastAPI", "REST APIs", "PostgreSQL", "MySQL", "MongoDB",
    "Pandas/NumPy", "Docker", "Git", "PyTorch", "TensorFlow", "scikit-learn", "LLMs",
    "XGBoost", "Computer vision", "MLOps", "Machine learning", "ROS", "Robotics",
    "Embedded systems", "Firmware", "Microcontrollers", "Sensor fusion",
}
# Real work that exists in her projects but is not on the resumes yet.
IN_PROJECTS_NOT_ON_RESUME = {"RAG", "Agents", "Testing", "Evaluation/metrics", "Vector databases"}


def clean_text(raw: str) -> str:
    """Turn HTML (possibly double-escaped) into plain text."""
    text = html.unescape(html.unescape(raw or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_skills(text: str) -> set:
    return {name for name, (_, rx) in SKILLS.items() if rx.search(text)}


def category_of(skill: str) -> str:
    return SKILLS[skill][0]
