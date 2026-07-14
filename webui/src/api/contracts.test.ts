import type { ProjectDetail, ShareVerifyResponse } from '../types/api';

type JsonBlobClient = {
  postBlob(path: string, body?: unknown): Promise<Blob>;
};

// Backend-derived contract fixtures kept dependency-free until the SPA adds a test runner.
export const verifiedShareFixture = {
  share: {
    id: 'share-123',
    paths: ['project/report.pdf'],
    created_by: 'owner',
    created_at: 1_700_000_000,
    allow_preview: true,
    download_count: 0,
    max_downloads: null,
    has_password: true,
    expired: false,
    expires_in_hours: 24,
  },
} satisfies ShareVerifyResponse;

export const projectDetailFixture = {
  name: 'project',
  path: 'projects/project',
  tags: [],
  notes: '',
  urls: [],
  total_size: 128,
  total_size_fmt: '128 B',
  file_count: 2,
  files: [{
    name: 'report.pdf',
    size: 128,
    size_fmt: '128 B',
    extension: '.pdf',
    category: 'document',
  }],
  images: [{
    name: 'cover.png',
    url: '/api/thumbnails/projects/project/cover.png?size=1920',
    thumb_url: '/api/thumbnails/projects/project/cover.png?size=512',
  }],
  thumbnail_url: '/api/thumbnails/projects/project/cover.png',
  modified: 1_700_000_000,
  download_url: '/api/download/projects/project',
} satisfies ProjectDetail;

export async function assertBatchDownloadUsesJson(client: JsonBlobClient): Promise<Blob> {
  return client.postBlob('download/batch', { paths: ['projects/project/report.pdf'] });
}

export function projectFileDownloadPath(project: ProjectDetail, fileName: string): string {
  return `/api/download/${encodeURIComponent([project.path, fileName].filter(Boolean).join('/'))}`;
}
