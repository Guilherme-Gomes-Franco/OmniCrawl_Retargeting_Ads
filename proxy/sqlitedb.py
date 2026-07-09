#!/usr/bin/env python3
import sqlite3
import zlib
import json

def connect(db_path):
    return _DB(db_path)

class _DB():
    def __init__(self, db_path):
        self.db = sqlite3.connect(db_path)
        # Main crawl table
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS crawl (
                browser TEXT,
                alexa_url TEXT,
                timeout INTEGER,
                data BLOB
            )''')
        
        # Dedicated table for JS Exceptions (Site Breakage Metric)
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS js_exceptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                browser TEXT,
                url TEXT,
                message TEXT,
                stack TEXT,
                fingerprint TEXT
            )''')
        self.db.commit()

    def insert(self, browser:str, alexa_url:str, timeout:bool, raw_data:dict):
        assert isinstance(raw_data, dict)
        payload = {
            'browser': browser,
            'alexa_url': alexa_url,
            'timeout': int(timeout),
            'data': zlib.compress(json.dumps(raw_data).encode())
        }
        self.db.execute('INSERT INTO crawl VALUES(:browser, :alexa_url, :timeout, :data)', payload)
        self.db.commit()

    # NEW: Method to batch insert exceptions for a specific site visit
    def insert_exceptions(self, browser, url, exceptions_list):
        cur = self.db.cursor()
        for err in exceptions_list:
            cur.execute(
                "INSERT INTO js_exceptions (browser, url, message, stack, fingerprint) VALUES (?, ?, ?, ?, ?)",
                (browser, url, err['message'], err['stack'], err['fingerprint'])
            )
        self.db.commit()

    def close(self):
        self.db.close()