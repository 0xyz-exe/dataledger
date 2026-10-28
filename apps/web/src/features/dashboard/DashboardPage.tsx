import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../../app/AuthContext';
import { dashboard } from '../../lib/api';
import { CheckCircle, AlertTriangle, XCircle, Database, GitMerge } from 'lucide-react';

function StatCard({ label, value, icon: Icon, color = 'blue' }: { label: string; value: unknown; icon: any; color?: string }) {
  const colors: Record<string, string> = {
    blue: 'bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400',
    green: 'bg-green-50 text-green-600 dark:bg-green-900/20 dark:text-green-400',
    amber: 'bg-amber-50 text-amber-600 dark:bg-amber-900/20 dark:text-amber-400',
    red: 'bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400',
  };
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-gray-500 dark:text-gray-400">{label}</span>
        <span className={`p-2 rounded-lg ${colors[color]}`}><Icon size={16} /></span>
      </div>
      <div className="text-2xl font-bold">{value?.toString() ?? '—'}</div>
    </div>
  );
}

export function DashboardPage() {
  const { workspace } = useAuth();
  const { data, isLoading, error } = useQuery({
    queryKey: ['dashboard', workspace?.id],
    queryFn: () => dashboard.get(workspace!.id),
    enabled: !!workspace,
  });

  if (isLoading) return <div className="p-8 text-gray-400">Loading dashboard…</div>;
  if (error) return <div className="p-8 text-red-500">Failed to load dashboard: {(error as Error).message}</div>;
  if (!data) return <div className="p-8 text-gray-400">No data available. Create a workspace to get started.</div>;

  const d = data as any;
  const matchRate = (d.match_rate * 100).toFixed(1);

  return (
    <div className="p-8 max-w-5xl">
      <div className="mb-6">
        <h1 className="text-xl font-bold">Overview</h1>
        <p className="text-sm text-gray-500 mt-1">{workspace?.name}</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Datasets" value={d.total_datasets} icon={Database} color="blue" />
        <StatCard label="Recon Jobs" value={d.total_jobs} icon={GitMerge} color="blue" />
        <StatCard label="Matched" value={d.matched_records} icon={CheckCircle} color="green" />
        <StatCard label="Pending Review" value={d.pending_review} icon={AlertTriangle} color="amber" />
      </div>

      {d.total_processed > 0 && (
        <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 mb-8">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">Match Rate</span>
            <span className="text-lg font-bold text-green-600">{matchRate}%</span>
          </div>
          <div className="w-full bg-gray-100 dark:bg-gray-800 rounded-full h-2">
            <div className="bg-green-500 rounded-full h-2 transition-all" style={{ width: `${matchRate}%` }} />
          </div>
          <p className="text-xs text-gray-400 mt-2">
            {d.matched_records} matched / {d.total_processed} total processed across all completed jobs.
          </p>
          <p className="text-xs text-gray-400">
            Definition: matched_records / (matched_records + unmatched_records)
          </p>
        </div>
      )}

      {d.recent_jobs?.length > 0 && (
        <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold mb-4">Recent Reconciliation Jobs</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-100 dark:border-gray-800">
                <th className="pb-2 font-medium">Name</th>
                <th className="pb-2 font-medium">Status</th>
                <th className="pb-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {d.recent_jobs.map((j: any) => (
                <tr key={j.id}>
                  <td className="py-2 font-medium">{j.name}</td>
                  <td className="py-2">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                      j.status === 'completed' ? 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400' :
                      j.status === 'failed' ? 'bg-red-50 text-red-700' :
                      j.status === 'completed_with_warnings' ? 'bg-amber-50 text-amber-700' :
                      'bg-gray-100 text-gray-600'
                    }`}>{j.status}</span>
                  </td>
                  <td className="py-2 text-gray-500">{new Date(j.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {d.total_jobs === 0 && (
        <div className="text-center py-16 text-gray-400">
          <GitMerge size={40} className="mx-auto mb-3 opacity-30" />
          <p className="font-medium">No reconciliation jobs yet</p>
          <p className="text-sm mt-1">Import datasets and create your first reconciliation job</p>
        </div>
      )}
    </div>
  );
}
