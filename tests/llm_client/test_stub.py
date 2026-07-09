from llm_client.stub import StubGenerator


def test_stub_generator_returns_markdown_with_job_title():
    generator = StubGenerator()
    job_url = "https://thehub.io/jobs/job-1"
    context = (
        f"--- Job 1 (id: job-1, url: {job_url}) ---\n"
        "Job Title: Backend Developer\nCompany: Acme\nJob Description: Python role"
    )

    answer = generator.generate(context, "backend roles in Denmark?")

    assert f"[Backend Developer]({job_url})" in answer
    assert "backend roles in Denmark?" in answer
    assert "**Senior Backend Engineer**" in answer
    assert answer.count("- ") >= 2


def test_stub_generator_ignores_closing_paren_after_job_url_in_context():
    generator = StubGenerator()
    job_url = "https://thehub.io/jobs/job-1"
    context = (
        f"--- Job 1 (id: job-1, url: {job_url}) ---\n"
        "Job Title: Sales Development Representative\nCompany: Acme"
    )

    answer = generator.generate(context, "sdr roles?")

    assert f"[Sales Development Representative]({job_url})" in answer
    assert f"{job_url}))" not in answer


def test_stub_generator_works_without_job_title():
    generator = StubGenerator()

    answer = generator.generate("", "hello?")

    assert "hello?" in answer
    assert "**Senior Backend Engineer**" in answer
