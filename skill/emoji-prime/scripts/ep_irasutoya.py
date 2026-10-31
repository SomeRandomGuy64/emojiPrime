"""Irasutoya: candidate search (in the catalog on the emoji-prime server) and illustration download.

The server keeps Irasutoya's post catalog (titles + image links, refreshed weekly from Irasutoya's public feed).
Illustrations are downloaded only when picked, straight from Irasutoya's image host into the cache.
"""
import os, time

from ep_api import search_many
from ep_common import CACHE, download

__all__ = ["search_many", "fetch_image", "DIGITS"]

DIR = os.path.join(CACHE, "irasutoya")
# 数字・番号のイラスト文字: numbers are shown digit by digit with these
DIGITS = {
    "0": "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEjeBhyphenhyphenNhvaVBP02X2E-1WDMQAiKVYGxVKEeSzmUg0n9wmndp2rsfiUTrx3OvnCwf0h5p9n5TBVlDYt-39VlAYiUyFyPhzhwhDFG02Dy5Q5Nc0kqMMbi0twNEAton0Ff9dhy8cJj1sM1PhuL/s400/number_0.png",
    "1": "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEjv49IPmlimX-9VQlNe5t9p5OJfSElvkpWEVgFt9SjQpCm_HDN06ULM-s0JZnahJ534o72gXXacoRYTZSDcttEO6fHo__twqN1G00JzdgYdKUbW28EjGfBcqF9ZCWbjRwMAc-JKs9-E1FnI/s400/number_1.png",
    "2": "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEgdhQb27AVdfgZ8utCpeON4bg9hQ0nCHhryg_4_aBpQbuDpaapic2mmbE620g8Kyymx7q_yxGczD0-CjrPbXNHNUcyz7I0ntP4j2qctPULceqLLN2YxrpA64Z5ByRNiPEvEvIkN22XLYqyn/s400/number_2.png",
    "3": "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEgcsiUfjDQFKD0LPqkkxN7u_hDPprXdTN83iwkVUkZyEzeYIGBKFpDvuhMjG8O63Sqf7T309yv9Jhq2DwMAL767epbzmfGpRm7QKBcnimQCj03_mDczMrB-rhwk_LgrnaUQn47ANVATM-Cm/s400/number_3.png",
    "4": "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEieBh827b8qI9-nxyXMQRABkgdAVyNIwd0k6DjGYJSm9UkYdxr16iPC3MIJKpcbf1aYhMbzvtCkmhghbJnEUFQUr5MnovecsDT2lsY1DSP7_0J_vmz6WZ2oq7VQ4V5SO3V8NsXMSQdEh9No/s400/number_4.png",
    "5": "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEj8AsvBis1u5JkCM3YA1nSrcvl8HhVNvZSKKtLHe2sKskAkbspWNuUw7E4dz2zRsq4GKXd8aKObZfdtcK9OyzLScVMHUBHKqkeV9Gqy96K0dWbRJOoq8P1unMzclz5gO3hFIF5-zj9erZVf/s400/number_5.png",
    "6": "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEj5qRctCvzFaqFWfPczBmArP5oYHEpmUieVd1-J_HXqbnL_jYIHN8CRoxAhyvUD0JvHZ4rssUNgen7CqOc75gtg75-zzD36o2VhVvSEWUURIUIgpF_MSTm5KwB48sJxXIbv72hMFzUiYAzD/s400/number_6.png",
    "7": "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEgFiR9j_H-V_fMkHHhC9x3vtkdbkfDdBXdMoLD0GB1jRhErwhC1Pi03GariIun8IbgRmydRenLlIzZhs3HgQ4sD7tnRiWWUdEiz-nOy99qQsteYw_iC08G3vbk2SA6dQ3W0kEH48HqNApxw/s400/number_7.png",
    "8": "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEhxRHde-AmLyk2nzSigRL_HWYJ4o2mANmXA2lU95zzm0rnfur_exVpuN1XWqeIuy8-wCGy_x6iq4iUGOji81MarzC_ZgBkWmo-tK5empTz4YUdBKVB03nTo9_vSZsIm1PSDuDIG8c11UMcY/s400/number_8.png",
    "9": "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEjjCUgdh2v7F_dJkRR1XKbnS3_wQa2xbtnC2vIDvkaJpkEO51pokQKou8bMqsf9DYLG3x98Stiap9o5y5PGhXcB84OcGW0JTUQa6WtRxIeTR_VX9uA_HuSA0LWyAgPV1zfDdYJlNsFrx1MJ/s400/number_9.png"
}


def fetch_image(url):
    dest = os.path.join(DIR, "img", os.path.basename(url.split("?")[0]))
    if not os.path.exists(dest) or os.path.getsize(dest) == 0:
        download(url, dest)
        time.sleep(0.3)
    return dest
