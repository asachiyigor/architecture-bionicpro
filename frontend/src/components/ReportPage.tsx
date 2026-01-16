import React, { useState } from 'react';
import { useAuth } from '../App';

interface ReportData {
  user_id: string;
  username: string;
  report_date: string;
  report_url?: string;
  data?: {
    summary: {
      total_days: number;
      total_usage_hours: number;
      avg_battery_level: number;
      total_movements: number;
      total_errors: number;
    };
    daily_data: Array<{
      date: string;
      usage_hours: number;
      battery_level: number;
      movements: number;
      errors: number;
    }>;
  };
  message?: string;
}

const ReportPage: React.FC = () => {
  const { isAuthenticated, isLoading, login, logout } = useAuth();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reportData, setReportData] = useState<ReportData | null>(null);

  const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

  const downloadReport = async () => {
    if (!isAuthenticated) {
      setError('Not authenticated');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setReportData(null);

      const response = await fetch(`${API_URL}/reports`, {
        credentials: 'include',  // Include session cookie
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (response.status === 401) {
        setError('Session expired. Please login again.');
        return;
      }

      if (response.status === 403) {
        setError('Access denied. You can only access your own reports.');
        return;
      }

      if (!response.ok) {
        throw new Error(`Failed to fetch report: ${response.statusText}`);
      }

      const data: ReportData = await response.json();
      setReportData(data);

      // If there's a CDN URL, optionally download the file
      if (data.report_url) {
        console.log('Report available at:', data.report_url);
      }

    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <div className="text-xl text-gray-600">Loading...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <div className="p-8 bg-white rounded-lg shadow-md text-center">
          <h1 className="text-2xl font-bold mb-6">BionicPRO Reports</h1>
          <p className="text-gray-600 mb-6">Please login to access your prosthetic usage reports.</p>
          <button
            onClick={login}
            className="px-6 py-3 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
          >
            Login with SSO
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100 p-4">
      <div className="w-full max-w-2xl p-8 bg-white rounded-lg shadow-md">
        <div className="flex justify-between items-center mb-6">
          <h1 className="text-2xl font-bold">BionicPRO Usage Reports</h1>
          <button
            onClick={logout}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 border border-gray-300 rounded hover:bg-gray-50"
          >
            Logout
          </button>
        </div>

        <div className="mb-6">
          <button
            onClick={downloadReport}
            disabled={loading}
            className={`w-full px-6 py-3 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors ${
              loading ? 'opacity-50 cursor-not-allowed' : ''
            }`}
          >
            {loading ? 'Generating Report...' : 'Download My Report'}
          </button>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-100 text-red-700 rounded-lg">
            {error}
          </div>
        )}

        {reportData && (
          <div className="space-y-4">
            {reportData.message && (
              <div className="p-4 bg-blue-100 text-blue-700 rounded-lg">
                {reportData.message}
              </div>
            )}

            {reportData.report_url && (
              <div className="p-4 bg-green-100 text-green-700 rounded-lg">
                <p className="font-semibold mb-2">Report generated successfully!</p>
                <a
                  href={reportData.report_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-green-800 underline hover:text-green-900"
                >
                  Download from CDN
                </a>
              </div>
            )}

            {reportData.data && (
              <div className="border rounded-lg p-4">
                <h2 className="text-lg font-semibold mb-4">Report Summary</h2>
                <div className="grid grid-cols-2 gap-4">
                  <div className="p-3 bg-gray-50 rounded">
                    <p className="text-sm text-gray-500">Total Days</p>
                    <p className="text-xl font-bold">{reportData.data.summary.total_days}</p>
                  </div>
                  <div className="p-3 bg-gray-50 rounded">
                    <p className="text-sm text-gray-500">Total Usage Hours</p>
                    <p className="text-xl font-bold">{reportData.data.summary.total_usage_hours.toFixed(1)}</p>
                  </div>
                  <div className="p-3 bg-gray-50 rounded">
                    <p className="text-sm text-gray-500">Avg Battery Level</p>
                    <p className="text-xl font-bold">{reportData.data.summary.avg_battery_level.toFixed(1)}%</p>
                  </div>
                  <div className="p-3 bg-gray-50 rounded">
                    <p className="text-sm text-gray-500">Total Movements</p>
                    <p className="text-xl font-bold">{reportData.data.summary.total_movements.toLocaleString()}</p>
                  </div>
                  <div className="p-3 bg-gray-50 rounded col-span-2">
                    <p className="text-sm text-gray-500">Total Errors</p>
                    <p className={`text-xl font-bold ${reportData.data.summary.total_errors > 0 ? 'text-red-600' : 'text-green-600'}`}>
                      {reportData.data.summary.total_errors}
                    </p>
                  </div>
                </div>

                {reportData.data.daily_data && reportData.data.daily_data.length > 0 && (
                  <div className="mt-6">
                    <h3 className="text-md font-semibold mb-3">Daily Breakdown</h3>
                    <div className="max-h-64 overflow-y-auto">
                      <table className="w-full text-sm">
                        <thead className="bg-gray-100 sticky top-0">
                          <tr>
                            <th className="p-2 text-left">Date</th>
                            <th className="p-2 text-right">Hours</th>
                            <th className="p-2 text-right">Battery</th>
                            <th className="p-2 text-right">Moves</th>
                            <th className="p-2 text-right">Errors</th>
                          </tr>
                        </thead>
                        <tbody>
                          {reportData.data.daily_data.map((day, index) => (
                            <tr key={index} className="border-b">
                              <td className="p-2">{day.date}</td>
                              <td className="p-2 text-right">{day.usage_hours?.toFixed(1) || '-'}</td>
                              <td className="p-2 text-right">{day.battery_level?.toFixed(0) || '-'}%</td>
                              <td className="p-2 text-right">{day.movements?.toLocaleString() || '-'}</td>
                              <td className={`p-2 text-right ${day.errors > 0 ? 'text-red-600' : ''}`}>
                                {day.errors || 0}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default ReportPage;
