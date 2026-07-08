from api.schemas import ChatSource, JobSearchHit


def test_job_search_hit_computes_job_url():
    hit = JobSearchHit(
        score=0.91,
        job_id="abc123",
        job_role="Backend Developer",
        country="Denmark",
        location="Copenhagen",
        remote=True,
        salary_type="paid",
        salary="Competitive",
        equity="Yes",
    )

    assert hit.job_url == "https://thehub.io/jobs/abc123"


def test_chat_source_computes_job_url():
    source = ChatSource(
        score=0.88,
        job_id="job-456",
        job_role="Backend Developer",
        document_text="Job details",
    )

    assert source.job_url == "https://thehub.io/jobs/job-456"
