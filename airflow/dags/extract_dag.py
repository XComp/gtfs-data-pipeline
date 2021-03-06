from datetime import datetime
import re
from typing import Callable

from airflow import DAG
from airflow.operators.dummy_operator import DummyOperator
from airflow.operators.subdag_operator import SubDagOperator
from airflow.operators import ExtractURLOperator, DownloadOperator, FakeDownloadOperator, ChecksumOperator

default_args = {
    "start_date": datetime(2019, 2, 21),
    "owner": "mapohl",
    "base_folder": "/usr/local/data"
}


def extract_vbb_download_url(**kwargs) -> str:
    url = kwargs["url"]
    response = kwargs["response"]

    match = re.search(
        r'<a href="(/media/download/[0-9]*)" title="GTFS-Paket [^\"]*" class="teaser-link[ ]+m-download">',
        response.content.decode("utf-8"))

    if not match:
        return

    return "{}://{}{}".format(url.scheme, url.netloc, match.group(1))


def extract_vrs_download_url(**kwargs) -> str:
    response = kwargs["response"]

    match = re.search(
        r'<a href="(http://[^"]*.zip)" target="_blank" class="external-link-new-window">GTFS-Daten[^<]*</a>',
        response.content.decode("utf-8"))

    if not match:
        return None

    return match.group(1)


def extract_kvv_download_url(**kwargs) -> str:
    response = kwargs["response"]

    match = re.search(
        r'<a href="(https://[^"]*.zip)" title="KVV GTFS-Daten" target="_blank" class="external-link-new-window">[^<]*</a>',
        response.content.decode("utf-8"))

    if not match:
        return None

    return match.group(1)


def create_provider_dag(
        parent_dag_id: str,
        provider_id: str,
        provider_description: str,
        provider_url: str,
        extract_func: Callable,
        check_url: bool,
        def_args: dict,
        source_file: str = None):
    provider_dag_id = "{}.{}".format(parent_dag_id, provider_id)

    def_args["provider_id"] = provider_id
    provider_dag = DAG(dag_id=provider_dag_id,
                       description="This DAG extracts the GTFS archive provided by {}.".format(provider_description),
                       default_args=def_args,
                       catchup=False)

    checksum_operator = ChecksumOperator(dag=provider_dag,
                                         task_id="checksum_task")

    if source_file:
        fake_download_operator = FakeDownloadOperator(dag=provider_dag,
                                                      task_id="download_task",
                                                      source_file=source_file)

        fake_download_operator >> checksum_operator
    else:
        extract_url_operator = ExtractURLOperator(dag=provider_dag,
                                                  task_id="extract_url_task",
                                                  url=provider_url,
                                                  extract_download_url=extract_func,
                                                  check_url=check_url)

        download_operator = DownloadOperator(dag=provider_dag,
                                             task_id="download_task")

        extract_url_operator >> download_operator >> checksum_operator

    return provider_dag


dag_metadata = [
    ("vbb", "VBB Berlin/Brandenburg",
     "http://www.vbb.de/unsere-themen/vbbdigital/api-entwicklerinfos/datensaetze",
     extract_vbb_download_url,
     False,
     None),
    ("vrs", "VRS Köln",
     "https://www.vrsinfo.de/fahrplan/oepnv-daten-fuer-webentwickler.html",
     extract_vrs_download_url,
     False,
     None),
    ("kvv", "Karlsruher Verkehrsverbund",
     "https://www.kvv.de/fahrt-planen/fahrplaene/open-data.html",
     extract_kvv_download_url,
     False,
     None)
]

main_dag_id = "gtfs_pipeline"
with DAG(dag_id=main_dag_id,
         description="Extracts the GTFS data from various sources.",
         schedule_interval=None,
         default_args=default_args,
         catchup=False) as dag:

    provider_start = DummyOperator(task_id="start")

    extract_tasks = []
    for prov_id, prov_desc, prov_url, prov_extract_func, prov_check_url, prov_source_file, in dag_metadata:
        sub_dag = create_provider_dag(parent_dag_id=main_dag_id,
                                      provider_id=prov_id,
                                      provider_description=prov_desc,
                                      provider_url=prov_url,
                                      extract_func=prov_extract_func,
                                      check_url=prov_check_url,
                                      def_args=default_args,
                                      source_file=prov_source_file)
        sub_dag_task = SubDagOperator(
            task_id=prov_id,
            dag=dag,
            subdag=sub_dag)

        provider_start >> sub_dag_task
