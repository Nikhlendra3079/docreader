import re
from operator import itemgetter

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
)
from langchain_core.runnables import RunnableLambda


def format_docs(docs) -> str:
    """Combine retrieved document chunks into a single context string."""
    return "\n\n".join(doc.page_content for doc in docs)


def clean_response(response: str) -> str:
    """Remove optional reasoning tags emitted by some local models."""
    return re.sub(
        r"<think>.*?</think>",
        "",
        response,
        flags=re.DOTALL,
    ).strip()


contextualize_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
Rewrite the user's latest question as a standalone question
using the conversation history.

Do not answer the question.
If the question is already self-contained, return it unchanged.
""",
        ),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{question}"),
    ]
)


prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a helpful assistant answering questions using retrieved documents.

Answer the user's question using the retrieved context.

When the user asks what a document says, or asks for a general summary,
summarize the relevant information present in the context. Include all
important points that are available; do not focus on only one fact.

Conversation history can help you understand references, but it is
not evidence about what the documents contain.

If the context does not contain enough information to answer the
question, clearly state what is missing. Do not claim that no document
was uploaded when relevant context is present.

Do not invent facts or claim that the documents say something they do not.

Context:
{context}
""",
        ),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{question}"),
    ]
)


def build_rag_chain(retriever, llm):
    """Build a shared LCEL RAG chain for the selected chat model."""

    question_rewriter = (
        contextualize_prompt
        | llm
        | StrOutputParser()
        | RunnableLambda(clean_response)
    )

    answer_chain = (
        prompt
        | llm
        | StrOutputParser()
        | RunnableLambda(clean_response)
    )

    def run_rag(inputs: dict) -> str:
        question = inputs["question"]
        chat_history = inputs.get("chat_history", [])

        # Rewrite follow-up questions so they can be searched independently.
        if chat_history:
            search_question = question_rewriter.invoke(
                {
                    "question": question,
                    "chat_history": chat_history,
                }
            )
        else:
            search_question = question

        # Retrieve relevant document chunks.
        docs = retriever.invoke(search_question)
        context = format_docs(docs)

        print("SEARCH QUESTION:", search_question)
        print("RETRIEVED CONTEXT:", repr(context))
        print("SOURCES:", docs)

        # Generate an answer using retrieved context and conversation history.
        return answer_chain.invoke(
            {
                "context": context,
                "question": question,
                "chat_history": chat_history,
            }
        )

    return RunnableLambda(run_rag)

async def stream_rag_chain(inputs: dict, retriever, llm):
    """Stream answer text after contextualizing and retrieving documents."""
    question = inputs["question"]
    chat_history = inputs.get("chat_history", [])

    question_rewriter = (
        contextualize_prompt
        | llm
        | StrOutputParser()
        | RunnableLambda(clean_response)
    )

    # Rewrite follow-up questions so retrieval can search independently.
    if chat_history:
        search_question = await question_rewriter.ainvoke(
            {
                "question": question,
                "chat_history": chat_history,
            }
        )
    else:
        search_question = question

    # Retrieve the relevant document chunks.
    docs = await retriever.ainvoke(search_question)
    context = format_docs(docs)

    print("STREAM SEARCH QUESTION:", search_question)
    print("STREAM RETRIEVED CONTEXT:", repr(context))
    print("STREAM SOURCES:", docs)

    # Stream answer text from the model.
    answer_chain = prompt | llm | StrOutputParser()

    async for token in answer_chain.astream(
        {
            "context": context,
            "question": question,
            "chat_history": chat_history,
        }
    ):
        if token:
            yield token