from llm_client.stub import StubGenerator


def test_stub_generator_returns_markdown_with_job_title():
    generator = StubGenerator()
    context = (
        "Job Title: Backend Developer\nCompany: Acme\nJob Description: Python role"
    )

    answer = generator.generate(context, "backend roles in Denmark?")

    assert "**Backend Developer**" in answer
    assert "backend roles in Denmark?" in answer
    assert "**Senior Backend Engineer**" in answer
    assert answer.count("- ") >= 2


def test_stub_generator_works_without_job_title():
    generator = StubGenerator()

    answer = generator.generate("", "hello?")

    assert "hello?" in answer
    assert "**Senior Backend Engineer**" in answer
