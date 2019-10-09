import unittest
from unittest.mock import patch, MagicMock

from lib.updaters.workUpdater import WorkUpdater
from sfrCore import Work
from lib.outputManager import OutputManager
from helpers.errorHelpers import DBError


class TestWorkUpdater(unittest.TestCase):
    @patch.object(WorkUpdater, 'parseData')
    def test_UpdaterInit(self, mockParser):
        mockParser.return_value = 'data'
        testUpdater = WorkUpdater({}, 'session')
        self.assertEqual(testUpdater.data, 'data')
        self.assertEqual(testUpdater.session, 'session')
        self.assertEqual(testUpdater.attempts, 0)

    def test_WorkParseData_nonNested(self):
        outData = WorkUpdater.parseData({
            'data': {
                'field1': 'jerry',
                'field2': 'hello'
            }
        })
        self.assertEqual(outData, {'field1': 'jerry', 'field2': 'hello'})

    def test_WorkParseData_nested(self):
        outData = WorkUpdater.parseData({
            'data': {
                'data': {
                    'field1': 'jerry',
                    'field2': 'hello'
                }
            }
        })
        self.assertEqual(outData, {'field1': 'jerry', 'field2': 'hello'})

    def test_getIdentifier(self):
        testUpdater = WorkUpdater({'data': {}}, 'session')
        testWork = MagicMock()
        testUUID = MagicMock()
        testUUID.hex = 'uuidString'
        testWork.uuid = testUUID
        testUpdater.work = testWork
        self.assertEqual(testUpdater.identifier, 'uuidString')

    @patch.object(Work, 'lookupWork', return_value='existing_work')
    def test_lookupRecord_success(self, mockLookup):
        testUpdater = WorkUpdater({'data': {}}, 'session')
        testUpdater.lookupRecord()
        self.assertEqual(testUpdater.work, 'existing_work')
        mockLookup.assert_called_once_with('session', [], None)

    @patch.dict('os.environ', {'UPDATE_STREAM': 'test'})
    @patch.object(Work, 'lookupWork', return_value=None)
    @patch.object(OutputManager, 'putKinesis')
    def test_lookupRecord_missing(self, mockPut, mockLookup):
        testUpdater = WorkUpdater({'data': {}}, 'session')
        with self.assertRaises(DBError):
            testUpdater.lookupRecord()
            mockLookup.assert_called_once_with('session', [], None)
            mockPut.assert_called_once_with(
                {'data': {}},
                'test',
                recType='work',
                attempts=1
            )

    @patch.object(Work, 'lookupWork', return_value=None)
    def test_lookupRecord_missing_retries_exceeded(self, mockLookup):
        testUpdater = WorkUpdater({'data': {}, 'attempts': 3}, 'session')
        with self.assertRaises(DBError):
            testUpdater.lookupRecord()
            mockLookup.assert_called_once_with('session', [], None)

    @patch.dict('os.environ', {'EPUB_STREAM': 'test'})
    @patch.object(OutputManager, 'putKinesis')
    def test_updateRecord(self, mockPut):
        mockWork = MagicMock()
        mockWork.update.return_value = ['deferred_epub']
        testUpdater = WorkUpdater({'data': {}}, 'session')
        testUpdater.work = mockWork

        testUpdater.updateRecord()
        mockWork.update.assert_called_once_with({}, session='session')
        mockPut.assert_called_once_with(
            'deferred_epub',
            'test',
            recType='item'
        )

    @patch('lib.updaters.workUpdater.datetime')
    def test_setUpdateTime(self, mockUTC):
        testUpdater = WorkUpdater({'data': {}}, 'session')
        testWork = MagicMock()
        testUpdater.work = testWork
        mockUTC.utcnow.return_value = 1000
        testUpdater.setUpdateTime()
        self.assertEqual(testUpdater.work.date_modified, 1000)
