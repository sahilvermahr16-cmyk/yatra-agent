from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
import config

load_dotenv()

llm = ChatOpenAI(model=config.LLM_MODEL, temperature=config.LLM_TEMPERATURE)


