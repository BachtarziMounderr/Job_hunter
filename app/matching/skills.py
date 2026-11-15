"""Auditable multilingual skill lexicon, with token boundaries and explicit aliases."""

import re
import unicodedata

SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "SQL": ("sql",),
    "JavaScript": ("javascript", "js"),
    "TypeScript": ("typescript",),
    "Java": ("java",),
    "C++": ("c++",),
    "C#": ("c#",),
    "C": ("c",),
    "React": ("react", "reactjs", "react.js"),
    "Next.js": ("next.js", "nextjs"),
    "Vue": ("vue", "vue.js", "vuejs"),
    "Angular": ("angular",),
    "Node.js": ("node.js", "nodejs"),
    "HTML": ("html", "html5"),
    "CSS": ("css", "css3"),
    "Git": ("git",),
    "FastAPI": ("fastapi",),
    "Flask": ("flask",),
    "Django": ("django",),
    "REST APIs": ("rest api", "rest apis", "restful", "apis rest"),
    "PostgreSQL": ("postgresql", "postgres"),
    "MySQL": ("mysql",),
    "MongoDB": ("mongodb",),
    "Redis": ("redis",),
    "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s"),
    "AWS": ("aws", "amazon web services"),
    "Azure": ("azure",),
    "GCP": ("gcp", "google cloud"),
    "Linux": ("linux",),
    "CI/CD": ("ci/cd", "continuous integration", "integration continue"),
    "pandas": ("pandas",),
    "NumPy": ("numpy",),
    "scikit-learn": ("scikit-learn", "scikit learn", "sklearn"),
    "PyTorch": ("pytorch", "py torch"),
    "TensorFlow": ("tensorflow",),
    "Keras": ("keras",),
    "XGBoost": ("xgboost",),
    "Spark": ("spark", "pyspark"),
    "Airflow": ("airflow",),
    "dbt": ("dbt",),
    "ETL": ("etl", "elt"),
    "Machine Learning": ("machine learning", "apprentissage automatique", "ml"),
    "Deep Learning": ("deep learning", "apprentissage profond"),
    "NLP": ("nlp", "natural language processing", "traitement du langage"),
    "BERT": ("bert",),
    "LSTM": ("lstm",),
    "Computer Vision": ("computer vision", "vision par ordinateur", "vision artificielle"),
    "LLM": ("llm", "llms", "large language model", "large language models"),
    "RAG": ("rag", "retrieval augmented generation", "retrieval-augmented generation"),
    "LangChain": ("langchain",),
    "Hugging Face": ("hugging face", "huggingface"),
    "Time Series": ("time series", "series temporelles"),
    "Feature Engineering": ("feature engineering",),
    "Model Evaluation": ("model evaluation", "evaluation de modeles"),
    "Recommendation Systems": ("recommendation systems", "recommendation system", "recommender"),
    "Anomaly Detection": ("anomaly detection", "detection d'anomalies"),
    "Image Segmentation": ("image segmentation", "segmentation d'images"),
    "Transfer Learning": ("transfer learning", "apprentissage par transfert"),
    "Streamlit": ("streamlit",),
    "Power BI": ("power bi", "powerbi"),
    "Tableau": ("tableau",),
    "MQTT": ("mqtt",),
    "IoT": ("iot", "aiot", "internet of things"),
    "LoRa": ("lora", "lorawan"),
    "ThingSpeak": ("thingspeak",),
    "Digital Twin": ("digital twin", "jumeau numerique"),
    "MobileNetV2": ("mobilenetv2",),
    "U-Net": ("u-net", "unet"),
    "SegNet": ("segnet",),
    "ResNet": ("resnet",),
    "VGG": ("vgg",),
}


def fold_text(text: str) -> str:
    """Make accented French and typographic punctuation comparable."""
    value = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in value if not unicodedata.combining(char)).replace("’", "'")


def extract_skills(text: str) -> list[str]:
    """Extract known skills; absence means unobserved, never proof of incompetence."""
    value = fold_text(text)
    found = []
    for skill, aliases in SKILL_ALIASES.items():
        if skill == "C" and value.strip() != "c":
            if not re.search(
                r"\b(python|langages?|languages?|programming|embedded|software)\b|c\+\+", value
            ):
                continue
        if any(
            re.search(r"(?<![\w+#'])" + re.escape(alias) + r"(?![\w+#'])", value)
            for alias in aliases
        ):
            found.append(skill)
    return sorted(found, key=str.casefold)


def skill_compatibility(
    candidate_skills: list[str], text: str
) -> tuple[float, list[str], list[str]]:
    observed = set(extract_skills(text))
    candidate = set(extract_skills("; ".join(candidate_skills)))
    matched = sorted(observed & candidate)
    missing = sorted(observed - candidate)
    # No detected skill requirement is uncertainty, not perfect compatibility.
    score = 100 * len(matched) / len(observed) if observed else 50.0
    return score, matched, missing
