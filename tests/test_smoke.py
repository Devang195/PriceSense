"""Exercise the packaged application without an external server."""
import math
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from pricesense_api_scraper.api import app

ROOT = Path(__file__).resolve().parents[1]

class ProjectSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_web_and_health(self):
        self.assertEqual(self.client.get('/health').json(), {'status': 'ok'})
        for route in ('/', '/static/app.js', '/static/styles.css', '/openapi.json'):
            self.assertEqual(self.client.get(route).status_code, 200, route)
        self.assertIn('PriceSense', self.client.get('/').text)

    def test_catalogue_and_history(self):
        r = self.client.get('/api/catalog').json()
        self.assertEqual(r['overview']['products'], 50)
        self.assertEqual(r['overview']['observations'], 54800)
        self.assertTrue(r['synthetic'])
        self.assertEqual(self.client.get('/prices/P001').json()['count'], 1096)
        self.assertEqual(self.client.get('/prices/invalid').status_code, 404)

    def test_forecast(self):
        response = self.client.get('/api/forecast', params={'product_id': 'P001', 'horizon': 30})
        self.assertEqual(response.status_code, 200, response.text[:500])
        result = response.json()
        self.assertEqual(len(result['forecast']), 30)
        self.assertEqual(len(result['interval']), 30)
        self.assertEqual(result['evaluation']['test_days'], 14)
        self.assertTrue(all(math.isfinite(x['price']) and x['price'] > 0 for x in result['forecast']))
        self.assertAlmostEqual(sum(result['deployment_weights'].values()), 1.0, places=6)
        self.assertTrue(result['adaptive']['available'])
        self.assertEqual(self.client.get('/api/forecast', params={'product_id': 'P001', 'horizon': 31}).status_code, 422)

    def test_csv_upload(self):
        example = ROOT / 'data' / 'sale_pattern_example.csv'
        with example.open('rb') as f:
            r = self.client.post('/api/upload/preview', files={'file': (example.name, f, 'text/csv')})
        self.assertEqual(r.status_code, 200, r.text[:500])
        self.assertGreater(r.json()['overview']['observations'], 0)
        self.assertEqual(self.client.post('/api/upload/preview', files={'file': ('bad.txt', b'abc', 'text/plain')}).status_code, 400)

if __name__ == '__main__':
    unittest.main()
