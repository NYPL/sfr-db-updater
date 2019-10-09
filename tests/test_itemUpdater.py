import unittest
from unittest.mock import patch, MagicMock

from lib.updaters.itemUpdater import ItemUpdater
from sfrCore import Item
from lib.outputManager import OutputManager
from helpers.errorHelpers import DBError


class TestWorkUpdater(unittest.TestCase):
    def test_UpdaterInit(self):
        testUpdater = ItemUpdater({'data': 'data'}, 'session')
        self.assertEqual(testUpdater.data, 'data')
        self.assertEqual(testUpdater.session, 'session')
        self.assertEqual(testUpdater.attempts, 0)

    def test_getIdentifier(self):
        testUpdater = ItemUpdater({'data': {}}, 'session')
        testItem = MagicMock()
        testItem.id = 1
        testUpdater.item = testItem
        self.assertEqual(testUpdater.identifier, 1)

    @patch.object(Item, 'lookup', return_value='existing_item')
    def test_lookupRecord_success(self, mockLookup):
        testUpdater = ItemUpdater({'data': {}}, 'session')
        testUpdater.lookupRecord()
        self.assertEqual(testUpdater.item, 'existing_item')
        mockLookup.assert_called_once_with('session', [], None)

    @patch.dict('os.environ', {'UPDATE_STREAM': 'test'})
    @patch.object(Item, 'lookup', return_value=None)
    @patch.object(OutputManager, 'putKinesis')
    def test_lookupRecord_missing(self, mockPut, mockLookup):
        testUpdater = ItemUpdater({'data': {}}, 'session')
        with self.assertRaises(DBError):
            testUpdater.lookupRecord()
            mockLookup.assert_called_once_with('session', [], None)
            mockPut.assert_called_once_with(
                {'data': {}},
                'test',
                recType='item',
                attempts=1
            )

    @patch.object(Item, 'lookup', return_value=None)
    def test_lookupRecord_missing_retries_exceeded(self, mockLookup):
        testUpdater = ItemUpdater({'data': {}, 'attempts': 3}, 'session')
        with self.assertRaises(DBError):
            testUpdater.lookupRecord()
            mockLookup.assert_called_once_with('session', [], None)

    @patch.dict('os.environ', {'EPUB_STREAM': 'test'})
    @patch.object(OutputManager, 'putKinesis')
    def test_updateRecord(self, mockPut):
        mockItem = MagicMock()
        testUpdater = ItemUpdater({'data': {}}, 'session')
        testUpdater.item = mockItem

        testUpdater.updateRecord()
        mockItem.update.assert_called_once_with('session', {})

    @patch('lib.updaters.itemUpdater.datetime')
    def test_setUpdateTime(self, mockUTC):
        testUpdater = ItemUpdater({'data': {}}, 'session')
        testItem = MagicMock()
        testUpdater.item = testItem
        mockUTC.utcnow.return_value = 1000
        testUpdater.setUpdateTime()
        self.assertEqual(testUpdater.item.instance.work.date_modified, 1000)