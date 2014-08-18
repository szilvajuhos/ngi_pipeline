import json
import requests
import unittest

from ngi_pipeline.database.classes import CharonSession, CHARON_BASE_URL, CharonError
from ngi_pipeline.tests.generate_test_data import generate_run_id

class TestCharonFunctions(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.session = CharonSession()
        # Project
        cls.p_id = "P100000"
        cls.p_name = "Y.Mom_14_01"
        # Sample
        cls.s_id = "{}_101".format(cls.p_id)
        # Libprep
        cls.l_id = "A"
        # Seqrun
        cls.sr_id = generate_run_id()
        cls.sr_reads = 1000000
        cls.sr_mac = 30

    def test_construct_charon_url(self):
        append_list = ["road","to","nowhere"]
        # This is a weird test because it's the same code as I'm testing but it also seems weird to code it worse
        finished_url = "{}/api/v1/{}".format(CHARON_BASE_URL,'/'.join([str(a) for a in append_list]))
        # The method expects not a list but individual args
        self.assertEqual(finished_url, CharonSession().construct_charon_url(*append_list))

    def test_validate_response_wrapper(self):
        session = self.session

        # 400 Invalid input data
        data = {"malformed": "data"}
        with self.assertRaises(CharonError):
            session.post(session.construct_charon_url("project"),
                         data=json.dumps(data))
        # Should work with RuntimeError as well
        with self.assertRaises(RuntimeError):
            session.post(session.construct_charon_url("project"),
                         data=json.dumps(data))

        # 404 Object not found
        p_id = "P000"
        with self.assertRaises(CharonError):
            session.get(session.construct_charon_url("project", p_id))

        # 405 Method not allowed
        with self.assertRaises(CharonError):
            # Should be GET
            session.post(session.construct_charon_url("projects"))

        # 409 Document revision conflict
        ## not sure how to fake this one


    # Test these -- can pass data dict directly
    def test_get(self):
        pass

    def test_post(self):
        pass

    def test_put(self):
        pass

    def test_delete(self):
        pass

    #
    # These functions all raise an Exception if there's any issue
    # They're numbered as they must occur in this order

    def test_01_project_create(self):
        self.session.project_create(self.p_id)

    def test_02_projects_get_all(self):
        self.session.projects_get_all()

    def test_03_project_update(self):
        self.session.project_update(projectid=self.p_id, name=self.p_name)

    def test_04_sample_create(self):
        self.session.sample_create(projectid=self.p_id, sampleid=self.s_id)

    def test_05_samples_get_all(self):
        self.session.samples_get_all(projectid=self.p_id)

    def test_06_sample_update(self):
        self.session.sample_update(projectid=self.p_id, sampleid=self.s_id,
                                   status="RUNNING")

    def test_07_libprep_create(self):
        self.session.libprep_create(projectid=self.p_id, sampleid=self.s_id,
                                    libprepid=self.l_id)

    def test_08_libpreps_get_all(self):
        self.session.libpreps_get_all(projectid=self.p_id, sampleid=self.s_id)

    def test_09_libprep_update(self):
        self.session.libprep_update(projectid=self.p_id, sampleid=self.s_id,
                                   libprepid=self.l_id, status="RUNNING")

    def test_10_seqrun_create(self):
        self.session.seqrun_create(projectid=self.p_id, sampleid=self.s_id,
                                    libprepid=self.l_id, seqrunid=self.sr_id,
                                    reads=self.sr_reads,
                                    mean_autosomal_coverage=self.sr_mac)

    def test_11_seqruns_get_all(self):
        self.session.seqruns_get_all(projectid=self.p_id, sampleid=self.s_id,
                                     libprepid=self.l_id)

    def test_12_seqrun_update(self):
        self.session.seqrun_update(projectid=self.p_id, sampleid=self.s_id,
                                   libprepid=self.l_id, seqrunid=self.sr_id,
                                   sequencing_status="RUNNING")


    def test_13_project_delete(self):
        self.session.project_delete(projectid=self.p_id)
