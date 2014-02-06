#coding: utf-8
import time
from datetime import datetime
from StringIO import StringIO
from multiprocessing.dummy import Pool as ThreadPool

import transaction
import scieloapi

import utils
import models
import meta_extractor
from checkin import PackageAnalyzer
from uploader import StaticScieloBackend


FILES_EXTENSION = ['xml', 'pdf',]
IMAGES_EXTENSION = ['tif', 'eps']
NAME_ZIP_FILE = 'images.zip'
STATIC_PATH = 'articles'


class CheckoutList(list):
    """
    Child class of list adapted to evaluate the type of the object when use the
    method append, if it's a models.Attempt change the boolean value of the
    attribute queued_checkout.
    """

    def append(self, item):
        """
        Add the param item on a parent list if is a expected type

        :param item: Any Attempt like object
        """
        if isinstance(item, models.Attempt):
            item.queued_checkout=True

        super(CheckoutList, self).append(item)


def get_static(attempt, ext):
    """
    Get the static files from the zip file
    Return a generator to a specific extension
    """

    pkg_analyzer = PackageAnalyzer(attempt.filepath)

    return pkg_analyzer.get_fps(ext)


def upload_static_files(attempt, conn_static):
    """
    Send the ``PDF``, ``XML`` files to the static server

    :param attempt: Attempt object
    :param cfg: cfguration file
    """
    uri_dict = {}
    dict_img = {}

    with conn_static as static:

        for ext in FILES_EXTENSION:
            for static_file in get_static(attempt, ext):
                uri = static.send(StringIO(static_file.read()),
                                  utils.get_static_path(STATIC_PATH,
                                            attempt.articlepkg.aid,
                                            static_file.name))
                uri_dict[ext] = uri

        for ext in IMAGES_EXTENSION:
            for static_file in get_static(attempt, ext):
                dict_img[static_file.name] = static_file.read()

        comp_img = utils.zip_files(dict_img)
        uri = static.send(comp_img,
                    utils.get_static_path(STATIC_PATH, attempt.articlepkg.aid,
                                           NAME_ZIP_FILE))

        uri_dict['img'] = uri

        return uri_dict


def upload_meta_front(attempt, client, uri_dict):
    """
    Send the extracted front to SciELO Manager

    :param attempt: Attempt object
    :param cfg: cfguration file
    :param uri_dict: dict content the uri to the static file
    """

    ppl =  meta_extractor.get_meta_ppl()

    xml = PackageAnalyzer(attempt.filepath).xml

    data = {
        'front': next(ppl.run(xml, rewrap=True)),
        'xml_url': uri_dict['xml'],
        'pdf_url': uri_dict['pdf'],
        'images_url': uri_dict['img'],
    }

    client.articles.post(data)


def checkout_procedure(item):
    """
    This function performs some operations related to the checkout
        - Upload static files to the backend
        - Upload the front metadata to the Manager
        - Set queued_checkout = False

    :param attempt: item (Attempt, cfg)
    """
    attempt, client, conn = item

    attempt.checkout_started_at = datetime.now()

    uri_dict = upload_static_files(attempt, conn)

    upload_meta_front(attempt, client, uri_dict)

    attempt.queued_checkout = False


def main(config):

    Session = models.Session
    Session.configure(bind=models.create_engine_from_config(config))
    session = Session()

    client = scieloapi.Client(config.get('manager', 'api_username'),
                              config.get('manager', 'api_key'),
                              config.get('manager', 'api_url'), 'v1')

    conn = StaticScieloBackend(config.get('static_server', 'username'),
                               config.get('static_server', 'password'),
                               config.get('static_server', 'path'),
                               config.get('static_server', 'host'))

    pool = ThreadPool()

    while True:

        attempts_checkout = session.query(models.Attempt).filter_by(
                                          proceed_to_checkout=True,
                                          pending_checkout=True).all()

        #Process only if exists itens
        if attempts_checkout:

            checkout_lst = CheckoutList()

            try:
                for attempt in attempts_checkout:
                    checkout_lst.append((attempt, client, conn))

                #Execute the checkout procedure for each item
                pool.map(checkout_procedure, checkout_lst)

                transaction.commit()
            except:
                transaction.abort()
                raise

        time.sleep(config.getint('checkout', 'time') * 60)

    pool.close


if __name__ == '__main__':
    config = utils.balaio_config_from_env()

    main(config)
