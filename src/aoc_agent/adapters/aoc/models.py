from pydantic import BaseModel


class AOCData(BaseModel):
    problem_html: str
    input_content: str
