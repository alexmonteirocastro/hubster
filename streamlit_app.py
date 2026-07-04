import time

import streamlit as st

from the_hub_client import (
    CountryCode,
    get_full_jobs_picture_by_country,
    scrape_job_offer_by_id,
)

sample_job_offer = scrape_job_offer_by_id("691c6aab3c37b217ff11eb79")


def stream_company_data():
    company_info = sample_job_offer.company_description

    answer = f"""
        Here's what the company is about: \n
        {company_info}
    """

    for word in answer.split(" "):
        yield word + " "
        time.sleep(0.02)


def stream_job_offer():
    for word in sample_job_offer.job_description.split(" "):
        yield word + " "
        time.sleep(0.02)


st.title("Welcome to the Hubster")

st.write("This simple app shows you insights from [The Hub](https://thehub.io/)")

jobs_tab, chat_tab = st.tabs(["Jobs", "Chat"])

with jobs_tab:
    st.header("Get the full picture of jobs in the country")

    selected_country = st.selectbox(
        label="Pick your country", options=[country.name for country in CountryCode]
    )

    full_picture = get_full_jobs_picture_by_country(
        country=CountryCode[selected_country]
    )

    st.markdown(
        f"**Total available jobs in {selected_country}: {full_picture.total_jobs}**"
    )

    table_data = {
        "Job Position": list(full_picture.jobs_per_role.model_dump().keys()),
        "openings": list(full_picture.jobs_per_role.model_dump().values()),
    }

    st.subheader("Breakdown by role")

    st.table(table_data)


with chat_tab:
    st.header("Smart chat")

    st.write("Use the AI-powered chat to ask questions about the jobs")

    chat_container = st.container()

    prompt = st.chat_input("Tell me about the company")

    if prompt:
        with chat_container:
            st.chat_message("User").write(prompt)
            with st.chat_message("Hubster"):
                with st.spinner("Hbster is getting the company infomation..."):
                    time.sleep(2)  # sleep for 2 seconds to simulate wait

                st.write_stream(stream_company_data)

                with st.spinner("Hbster is fetching the job offer..."):
                    time.sleep(2)  # sleep for 2 seconds to simulate wait

                st.write_stream(stream_job_offer)
