import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../app/AuthContext';
import { reconciliation, datasets } from '../../lib/api';
import { Plus, Play, GitMerge, Download, ChevronRight } from 'lucide-react';

function StatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    completed: 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400',
    completed_with_warnings: 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400',
    failed: 'bg-red-50 text-red-700',
    running: 'bg-blue-50 text-blue-700 dark:bg-blue-900/20',
    queued: 'bg-gray-100 text-gray-600',
    draft: 'bg-gray-100 text-gray-600',
    cancelled: 'bg-gray-100 text-gray-500',
  };
  return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${cls[status] || cls.draft}`}>{status.replace('_', ' ')}</span>;
}

function CreateJobModal({ wsId, onClose }: { wsId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: dsList } = useQuery({
    queryKey: ['datasets', wsId],
    queryFn: () => datasets.list(wsId),
  });

  const [name, setName] = useState('');
  const [dsA, setDsA] = useState('');
  const [dsB, setDsB] = useState('');
  const [matchFields, setMatchFields] = useState('reference_id');
  const [amountTol, setAmountTol] = useState('');
  const [dateTol, setDateTol] = useState('0');
  const [error, setError] = useState('');

  const mut = useMutation({
    mutationFn: () => reconciliation.create(wsId, {
      name,
      dataset_a_id: dsA,
      dataset_b_id: dsB,
      matching_rules: {
        match_fields: matchFields.split(',').map(s => s.trim()).filter(Boolean),
        strategy: 'exact',
        amount_tolerance: amountTol || null,
        date_tolerance_days: parseInt(dateTol) || 0,
        case_sensitive: false,
        null_handling: 'exclude',
        amount_field: 'amount',
        date_field: 'transaction_date',
        fuzzy_threshold: 0.85,
      },
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['recon', wsId] }); onClose(); },
    onError: (e: Error) => setError(e.message),
  });

  const readyDatasets = dsList?.filter(d => d.import_status === 'completed') || [];

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 w-full max-w-md p-6 shadow-xl">
        <h2 className="text-base font-semibold mb-4">New Reconciliation Job</h2>
        {error && <div className="mb-3 p-3 bg-red-50 dark:bg-red-900/20 text-red-700 text-sm rounded-lg">{error}</div>}
        <div className="space-y-3">
          <input placeholder="Job name" value={name} onChange={e => setName(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />

          <div>
            <label className="block text-xs text-gray-500 mb-1">Source A</label>
            <select value={dsA} onChange={e => setDsA(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">Select dataset…</option>
              {readyDatasets.map(d => <option key={d.id} value={d.id}>{d.name} ({d.row_count} rows)</option>)}
            </select>
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">Source B</label>
            <select value={dsB} onChange={e => setDsB(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">Select dataset…</option>
              {readyDatasets.map(d => <option key={d.id} value={d.id}>{d.name} ({d.row_count} rows)</option>)}
            </select>
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">Match fields (comma-separated)</label>
            <input value={matchFields} onChange={e => setMatchFields(e.target.value)}
              placeholder="reference_id, transaction_date"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Amount tolerance</label>
              <input value={amountTol} onChange={e => setAmountTol(e.target.value)}
                placeholder="e.g. 100"
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Date tolerance (days)</label>
              <input type="number" value={dateTol} onChange={e => setDateTol(e.target.value)} min="0"
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800">Cancel</button>
          <button onClick={() => mut.mutate()} disabled={!name || !dsA || !dsB || mut.isPending}
            className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-lg">
            {mut.isPending ? 'Creating…' : 'Create Job'}
          </button>
        </div>
      </div>
    </div>
  );
}

function ResultsPanel({ wsId, jobId }: { wsId: string; jobId: string }) {
  const [category, setCategory] = useState('');
  const { data } = useQuery({
    queryKey: ['recon-results', wsId, jobId, category],
    queryFn: () => reconciliation.results(wsId, jobId, 1, category || undefined),
  });

  const categories = ['matched', 'missing_in_a', 'missing_in_b', 'amount_mismatch', 'date_mismatch', 'ambiguous_match'];

  return (
    <div className="mt-4">
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span className="text-sm font-medium">Filter:</span>
        <button onClick={() => setCategory('')} className={`px-2 py-1 text-xs rounded-full ${!category ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>All</button>
        {categories.map(c => (
          <button key={c} onClick={() => setCategory(c)}
            className={`px-2 py-1 text-xs rounded-full ${category === c ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
            {c.replace(/_/g, ' ')}
          </button>
        ))}
      </div>

      <div className="space-y-2 max-h-80 overflow-y-auto">
        {data?.results?.map((r: any, i: number) => (
          <div key={i} className={`p-3 rounded-lg border text-xs ${
            r.category === 'matched' ? 'border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-900/10' :
            r.category?.includes('missing') ? 'border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-900/10' :
            'border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-900/10'
          }`}>
            <div className="font-medium mb-1">{r.category?.replace(/_/g, ' ')}</div>
            <div className="text-gray-600 dark:text-gray-400">{r.explanation}</div>
            {r.diff_fields?.length > 0 && (
              <div className="mt-1 text-gray-500">Diff fields: {r.diff_fields.join(', ')}</div>
            )}
          </div>
        ))}
        {data?.results?.length === 0 && <div className="text-gray-400 text-center py-4">No results for this filter</div>}
      </div>
    </div>
  );
}

export function ReconciliationPage() {
  const { workspace } = useAuth();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [selectedJob, setSelectedJob] = useState<string | null>(null);

  const { data: jobs, isLoading } = useQuery({
    queryKey: ['recon', workspace?.id],
    queryFn: () => reconciliation.list(workspace!.id),
    enabled: !!workspace,
    refetchInterval: 5000,
  });

  const runMut = useMutation({
    mutationFn: (jobId: string) => reconciliation.run(workspace!.id, jobId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['recon', workspace?.id] }),
  });

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold">Reconciliation Jobs</h1>
          <p className="text-sm text-gray-500 mt-1">Compare datasets and detect discrepancies</p>
        </div>
        <button onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium">
          <Plus size={16} />New Job
        </button>
      </div>

      {isLoading && <div className="text-gray-400">Loading…</div>}

      {!isLoading && jobs?.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <GitMerge size={40} className="mx-auto mb-3 opacity-30" />
          <p className="font-medium">No jobs yet</p>
          <p className="text-sm mt-1">Import datasets first, then create a reconciliation job</p>
        </div>
      )}

      <div className="space-y-3">
        {jobs?.map(job => (
          <div key={job.id} className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-medium">{job.name}</span>
                  <StatusBadge status={job.status} />
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  {new Date(job.created_at).toLocaleString()}
                  {job.total_processed > 0 && (
                    <span className="ml-2">
                      · {job.matched_count} matched · {job.unmatched_count} unmatched · {job.discrepancy_count} discrepancies
                    </span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {job.status === 'draft' && (
                  <button onClick={() => runMut.mutate(job.id)} disabled={runMut.isPending}
                    className="flex items-center gap-1 px-3 py-1.5 bg-green-600 hover:bg-green-700 disabled:opacity-60 text-white rounded-lg text-xs font-medium">
                    <Play size={12} />Run
                  </button>
                )}
                {(job.status === 'completed' || job.status === 'completed_with_warnings') && (
                  <>
                    <button onClick={() => reconciliation.export(workspace!.id, job.id)}
                      className="flex items-center gap-1 px-3 py-1.5 border border-gray-300 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 rounded-lg text-xs">
                      <Download size={12} />Export
                    </button>
                    <button onClick={() => setSelectedJob(selectedJob === job.id ? null : job.id)}
                      className="flex items-center gap-1 px-3 py-1.5 border border-gray-300 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 rounded-lg text-xs">
                      <ChevronRight size={12} className={selectedJob === job.id ? 'rotate-90' : ''} />Results
                    </button>
                  </>
                )}
              </div>
            </div>
            {selectedJob === job.id && <ResultsPanel wsId={workspace!.id} jobId={job.id} />}
          </div>
        ))}
      </div>

      {showCreate && <CreateJobModal wsId={workspace!.id} onClose={() => setShowCreate(false)} />}
    </div>
  );
}
