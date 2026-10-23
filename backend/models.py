from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Section(StrictModel):
    title: str
    kind: Literal['concept', 'steps', 'case', 'comparison', 'process', 'warning']
    markdown: str
    keypoints: list[str]
    source_ids: list[str]

class Note(StrictModel):
    title: str = Field(min_length=1)
    subtitle: str
    overview: str = Field(min_length=1)
    sections: list[Section] = Field(min_length=1)
    limitations: list[str]
    conclusion: str

class Chapter(StrictModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    title: str
    objective: str
    source_ids: list[str]

class Course(StrictModel):
    title: str
    description: str
    chapters: list[Chapter] = Field(min_length=1, max_length=16)
    @model_validator(mode='after')
    def unique_ids(self):
        if len({c.id for c in self.chapters}) != len(self.chapters):
            raise ValueError('章节编号重复')
        return self

class Question(StrictModel):
    id: str
    kind: Literal['single', 'multiple', 'boolean']
    prompt: str
    options: list[str] = Field(min_length=2, max_length=6)
    correct: list[int] = Field(min_length=1)
    explanation: str
    source_ids: list[str]
    @model_validator(mode='after')
    def valid_answer(self):
        if len(set(self.correct)) != len(self.correct) or any(i < 0 or i >= len(self.options) for i in self.correct):
            raise ValueError('答案必须对应有效选项')
        if self.kind != 'multiple' and len(self.correct) != 1:
            raise ValueError('单选和判断题必须只有一个答案')
        if self.kind == 'boolean' and len(self.options) != 2:
            raise ValueError('判断题只能有两个选项')
        return self

class Quiz(StrictModel):
    title: str
    questions: list[Question] = Field(min_length=1, max_length=20)
    @model_validator(mode='after')
    def unique_ids(self):
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError('题目编号重复')
        return self

class Lesson(StrictModel):
    title: str
    objective: str
    markdown: str
    summary: str
    source_ids: list[str]
    questions: list[Question] = Field(min_length=1, max_length=5)
    @model_validator(mode='after')
    def unique_ids(self):
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError('题目编号重复')
        return self

class Extracted(StrictModel):
    title: str
    segments: list[dict]
    scope: str
    warnings: list[str]

class VisualFrame(StrictModel):
    description: str
    visible_text: str
    caveats: str

class ImportRequest(BaseModel):
    kind: Literal['text', 'url']
    content: str = Field(min_length=1)
    title: str = Field(default='', max_length=300)
    instructions: str = Field(default='', max_length=4000)
    format: Literal['markdown', 'poster', 'mindmap'] = 'poster'
    mode: Literal['summary', 'course'] = 'summary'

class GenerateRequest(BaseModel):
    kind: Literal['summary', 'course', 'lesson', 'quiz', 'stage', 'vision']
    chapter_id: str = ''
    boundary: int = 0

class EditRequest(BaseModel):
    revision: int
    note: Note

class ProgressRequest(StrictModel):
    # Only changed answers and newly completed chapters cross the wire.
    epoch: int = 0
    completed: list[str] = Field(default_factory=list, max_length=16)
    answers: dict[str, list[int] | None] = Field(default_factory=dict, max_length=500)
    last_chapter: str | None = None

Provider = Literal['deepseek','moonshot','kimi_code','glm','custom','ollama','lmstudio','local_custom']

class ModelProfile(StrictModel):
    base_url: str = Field(max_length=500)
    model: str = Field(default='',max_length=200)
    api_key: SecretStr | None = Field(default=None,max_length=4096)
    clear_api_key: bool = False
    supports_images: bool = False
    output_format: Literal['json_object','json_schema','prompt'] = 'json_object'
    max_tokens: int = Field(default=8192,ge=256,le=65536)
    context_chars: int = Field(default=40000,ge=4000,le=120000)
    reasoning_effort: Literal['default','low','medium','high','xhigh','max'] = 'default'

class ModelConnectionRequest(StrictModel):
    provider: Provider
    profile: ModelProfile

class SettingsRequest(BaseModel):
    whisper_model: Literal['mlx-community/whisper-large-v3-turbo', 'mlx-community/whisper-small-mlx']
    model: str = Field(default='', max_length=100)
    generation_backend: Literal['codex','api','local'] = 'codex'
    api_provider: Literal['deepseek','moonshot','kimi_code','glm','custom'] = 'deepseek'
    local_provider: Literal['ollama','lmstudio','local_custom'] = 'ollama'
    providers: dict[Provider,ModelProfile] | None = None
