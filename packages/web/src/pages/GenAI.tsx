// Unified GenAI page: on-demand generation form on top, prompt library
// (blocks + presets) tucked into an "Advanced" expansion below.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ConfirmDialog } from '../components/Dialog'
import { Button, Expansion, SelectField, Switch, TextArea, TextField } from '../components/fields'
import { useNotify } from '../components/Toast'
import { Badge, EmptyNote } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { formatRelative } from '../lib/format'
import {
  DEFAULT_GEMINI_MODEL,
  PROMPT_BLOCK_KINDS,
  type GenerationTask,
  type PromptBlock,
  type PromptBlockKind,
  type PromptPreset,
} from '../lib/types'

const SUBJECT_MAX_CHARS = 200
const BLOCK_PREVIEW_CHARS = 80

function errMessage(err: unknown): string {
  return err instanceof ApiError ? err.detail || err.message : String(err)
}

export function GenAI() {
  return (
    <>
      <GenerateSection />
      <RecentGenerations />
      <div style={{ height: 24 }} />
      <AdvancedSection />
    </>
  )
}

// --- Recent generations ---------------------------------------------------------

const TASK_BADGE: Record<GenerationTask['status'], { tone: 'ok' | 'warn' | 'muted' | 'accent'; label: string }> = {
  queued: { tone: 'muted', label: 'Queued' },
  running: { tone: 'accent', label: 'Running' },
  completed: { tone: 'ok', label: 'Done' },
  failed: { tone: 'warn', label: 'Failed' },
}

function RecentGenerations() {
  const { data: tasks } = useQuery({
    queryKey: ['generation-tasks'],
    queryFn: () => api.listGenerationTasks(20),
    // Poll quickly while something is in flight, lazily otherwise.
    refetchInterval: (query) =>
      query.state.data?.some((t) => t.status === 'queued' || t.status === 'running') ? 3000 : 15000,
  })

  if (!tasks || tasks.length === 0) return null

  return (
    <div className="bento-tile w-full" style={{ padding: 20 }}>
      <div className="col gap-0">
        <span className="ink-eyebrow">Status</span>
        <h3 className="ink-h3">Recent generations</h3>
      </div>
      <span className="ink-small">History covers the current API process — restarts clear it, images are kept.</span>
      <div className="col w-full gap-2">
        {tasks.map((task) => {
          const badge = TASK_BADGE[task.status]
          return (
            <div
              key={task.task_id}
              className="row w-full items-center gap-3"
              style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 8 }}
            >
              <Badge tone={badge.tone}>{badge.label}</Badge>
              <div className="col flex-1 gap-0">
                {task.image_id ? (
                  <Link to={`/images/${task.image_id}`} style={{ color: 'var(--ink-accent)', fontSize: 14 }}>
                    {task.subject}
                  </Link>
                ) : (
                  <span style={{ fontSize: 14 }}>{task.subject}</span>
                )}
                <span className="ink-small">{task.error ?? task.detail ?? ''}</span>
              </div>
              <span className="ink-small" style={{ whiteSpace: 'nowrap' }}>
                {formatRelative(task.finished_at ?? task.created_at)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// --- Generate -----------------------------------------------------------------

function GenerateSection() {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const { data: profiles } = useQuery({ queryKey: ['device-profiles'], queryFn: api.listDeviceProfiles })
  const { data: presets } = useQuery({ queryKey: ['prompt-presets'], queryFn: api.listPromptPresets })

  const [subject, setSubject] = useState('')
  const [profileId, setProfileId] = useState('')
  const [presetId, setPresetId] = useState('')
  const [portrait, setPortrait] = useState(true)
  const [pushImmediately, setPushImmediately] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!profileId && profiles?.length) setProfileId(profiles.find((p) => p.is_default)?.id ?? profiles[0].id)
  }, [profiles, profileId])
  useEffect(() => {
    if (!presetId && presets?.length) setPresetId(presets.find((p) => p.is_default)?.id ?? presets[0].id)
  }, [presets, presetId])

  const submit = async () => {
    if (!subject.trim()) return setError('Subject is required')
    if (!profileId) return setError('Target device profile is required')
    try {
      const result = await api.generateImage({
        subject: subject.trim(),
        target_device_profile_id: profileId,
        preset_id: presetId || null,
        orientation: portrait ? 'portrait' : 'landscape',
        push_immediately: pushImmediately,
      })
      notify(`Queued (task ${result.task_id}) — image will appear shortly.`, 'positive')
      setSubject('')
      setError('')
      queryClient.invalidateQueries({ queryKey: ['generation-tasks'] })
    } catch (err) {
      setError(`Generation failed: ${errMessage(err)}`)
    }
  }

  return (
    <section className="col w-full gap-4">
      <div className="col gap-0">
        <span className="ink-eyebrow">GenAI</span>
        <h2 className="ink-h2">Generate an image</h2>
        <p className="ink-body ink-muted" style={{ maxWidth: 640, margin: 0 }}>
          Describe what you want to see. The API renders it with Gemini and dispatches the result to a random matching
          device as soon as it's ready.
        </p>
      </div>

      <div className="bento-tile w-full" style={{ padding: 24 }}>
        <div className="ink-form-section w-full">
          <TextArea
            label="Subject"
            value={subject}
            onChange={setSubject}
            rows={4}
            maxLength={SUBJECT_MAX_CHARS}
            counter
            autoFocus
            placeholder="e.g. Ada Lovelace, a fox in a snowy forest, a vintage espresso machine on a kitchen counter…"
            style={{ fontSize: 15 }}
          />
          <div className="ink-form-row w-full">
            <SelectField
              label="Target device profile"
              value={profileId}
              onChange={setProfileId}
              options={(profiles ?? []).map((p) => ({ value: p.id, label: `${p.name} (${p.width}x${p.height})` }))}
            />
            <SelectField
              label="Prompt preset"
              value={presetId}
              onChange={setPresetId}
              options={(presets ?? []).map((p) => ({ value: p.id, label: p.name }))}
            />
          </div>
          <div className="ink-form-row items-center w-full">
            <Switch label="Portrait orientation" checked={portrait} onChange={setPortrait} />
            <Switch label="Push immediately when ready" checked={pushImmediately} onChange={setPushImmediately} />
          </div>
        </div>
      </div>

      <span className="ink-form-error">{error}</span>

      <div className="ink-action-bar">
        <Button primary icon="auto_awesome" onClick={submit}>
          Generate
        </Button>
      </div>
    </section>
  )
}

// --- Advanced: prompt library -----------------------------------------------------

function AdvancedSection() {
  const { data: blocks } = useQuery({ queryKey: ['prompt-blocks'], queryFn: api.listPromptBlocks })
  const { data: presets } = useQuery({ queryKey: ['prompt-presets'], queryFn: api.listPromptPresets })

  return (
    <Expansion title="Advanced — prompt library">
      <span className="ink-small" style={{ marginBottom: 8 }}>
        Power-user controls. Blocks are the reusable text fragments that make up a preset; presets are what the
        generate form and Gemini batch jobs reference. Composition blocks may include {'{subject}'}.
      </span>
      <BlocksCard blocks={blocks ?? []} />
      <PresetsCard presets={presets ?? []} blocks={blocks ?? []} />
    </Expansion>
  )
}

function BlocksCard({ blocks }: { blocks: PromptBlock[] }) {
  const sorted = [...blocks].sort((a, b) => a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name))
  return (
    <div className="bento-tile w-full" style={{ padding: 20 }}>
      <h3 className="ink-h3">Blocks</h3>
      {sorted.length === 0 && <EmptyNote>(none)</EmptyNote>}
      {sorted.map((block) => <BlockRow key={block.id} block={block} />)}
      <hr style={{ width: '100%', border: 'none', borderTop: '1px solid var(--ink-border)', margin: '12px 0' }} />
      <NewBlockForm />
    </div>
  )
}

function BlockRow({ block }: { block: PromptBlock }) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [name, setName] = useState(block.name)
  const [text, setText] = useState(block.text)
  const [isDefault, setIsDefault] = useState(block.is_default)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const preview = block.text.slice(0, BLOCK_PREVIEW_CHARS) + (block.text.length > BLOCK_PREVIEW_CHARS ? '…' : '')
  const header = `${block.kind.toUpperCase()}  ·  ${block.name}${block.is_default ? ' · default' : ''}`

  const save = async () => {
    try {
      await api.updatePromptBlock(block.id, { name, text, is_default: isDefault })
    } catch (err) {
      notify(`Save failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify('Saved', 'positive')
    queryClient.invalidateQueries({ queryKey: ['prompt-blocks'] })
  }

  const doDelete = async () => {
    setConfirmDelete(false)
    try {
      await api.deletePromptBlock(block.id)
    } catch (err) {
      notify(`Delete failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify('Deleted', 'positive')
    queryClient.invalidateQueries({ queryKey: ['prompt-blocks'] })
  }

  return (
    <Expansion title={header} bordered>
      <span className="ink-small">{preview}</span>
      <TextField label="Name" value={name} onChange={setName} />
      <TextArea label="Text" value={text} onChange={setText} rows={4} />
      <Switch label="Use as default for this kind" checked={isDefault} onChange={setIsDefault} />
      <div className="row w-full justify-end gap-2">
        <Button flat icon="save" onClick={save}>
          Save
        </Button>
        <Button flat danger icon="delete" onClick={() => setConfirmDelete(true)}>
          Delete
        </Button>
      </div>
      <ConfirmDialog
        open={confirmDelete}
        message={`Delete block '${block.name}'?`}
        destructive
        confirmLabel="Delete"
        onConfirm={doDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </Expansion>
  )
}

function NewBlockForm() {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<PromptBlockKind>('style')
  const [name, setName] = useState('')
  const [text, setText] = useState('')

  const create = async () => {
    if (!name || !text) {
      notify('Name and text are required', 'warning')
      return
    }
    try {
      await api.createPromptBlock({ kind, name, text, is_default: false })
    } catch (err) {
      notify(`Create failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify('Created', 'positive')
    setName('')
    setText('')
    queryClient.invalidateQueries({ queryKey: ['prompt-blocks'] })
  }

  return (
    <Expansion title="Add new block" bordered>
      <SelectField
        label="Kind"
        value={kind}
        onChange={(v) => setKind(v as PromptBlockKind)}
        options={PROMPT_BLOCK_KINDS.map((k) => ({ value: k, label: k }))}
      />
      <TextField label="Name" value={name} onChange={setName} />
      <TextArea label="Text" value={text} onChange={setText} rows={4} />
      <div className="row">
        <Button primary icon="add" onClick={create}>
          Add block
        </Button>
      </div>
    </Expansion>
  )
}

function blocksByKind(blocks: PromptBlock[]): Map<PromptBlockKind, PromptBlock[]> {
  const map = new Map<PromptBlockKind, PromptBlock[]>(PROMPT_BLOCK_KINDS.map((k) => [k, []]))
  for (const block of blocks) {
    map.get(block.kind as PromptBlockKind)?.push(block)
  }
  return map
}

function PresetsCard({ presets, blocks }: { presets: PromptPreset[]; blocks: PromptBlock[] }) {
  const byKind = blocksByKind(blocks)
  const nameById = new Map(blocks.map((b) => [b.id, b.name]))
  return (
    <div className="bento-tile w-full" style={{ padding: 20 }}>
      <h3 className="ink-h3">Presets</h3>
      {presets.length === 0 && <EmptyNote>(none)</EmptyNote>}
      {presets.map((preset) => <PresetRow key={preset.id} preset={preset} byKind={byKind} nameById={nameById} />)}
      <hr style={{ width: '100%', border: 'none', borderTop: '1px solid var(--ink-border)', margin: '12px 0' }} />
      <NewPresetForm byKind={byKind} />
    </div>
  )
}

function PresetRow({
  preset,
  byKind,
  nameById,
}: {
  preset: PromptPreset
  byKind: Map<PromptBlockKind, PromptBlock[]>
  nameById: Map<string, string>
}) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [name, setName] = useState(preset.name)
  const [model, setModel] = useState(preset.model_name || DEFAULT_GEMINI_MODEL)
  const [selection, setSelection] = useState<Record<PromptBlockKind, string>>({
    style: preset.style_block_id,
    palette: preset.palette_block_id,
    legibility: preset.legibility_block_id,
    composition: preset.composition_block_id,
    background: preset.background_block_id,
  })
  const [isDefault, setIsDefault] = useState(preset.is_default)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const summary = PROMPT_BLOCK_KINDS.map(
    (kind) => nameById.get(preset[`${kind}_block_id` as const]) ?? '?',
  ).join(' / ')

  const save = async () => {
    try {
      await api.updatePromptPreset(preset.id, {
        name,
        model_name: model || DEFAULT_GEMINI_MODEL,
        ...Object.fromEntries(PROMPT_BLOCK_KINDS.map((kind) => [`${kind}_block_id`, selection[kind]])),
        is_default: isDefault,
      })
    } catch (err) {
      notify(`Save failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify('Saved', 'positive')
    queryClient.invalidateQueries({ queryKey: ['prompt-presets'] })
  }

  const doDelete = async () => {
    setConfirmDelete(false)
    try {
      await api.deletePromptPreset(preset.id)
    } catch (err) {
      notify(`Delete failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify('Deleted', 'positive')
    queryClient.invalidateQueries({ queryKey: ['prompt-presets'] })
  }

  return (
    <Expansion title={`${preset.name}${preset.is_default ? ' · default' : ''}`} bordered>
      <span className="ink-small">{summary}</span>
      <TextField label="Name" value={name} onChange={setName} />
      <TextField label="Gemini model" value={model} onChange={setModel} />
      {PROMPT_BLOCK_KINDS.map((kind) => (
        <SelectField
          key={kind}
          label={kind[0].toUpperCase() + kind.slice(1)}
          value={selection[kind]}
          onChange={(v) => setSelection({ ...selection, [kind]: v })}
          options={(byKind.get(kind) ?? []).map((b) => ({ value: b.id, label: b.name }))}
        />
      ))}
      <Switch label="Default preset" checked={isDefault} onChange={setIsDefault} />
      <div className="row w-full justify-end gap-2">
        <Button flat icon="save" onClick={save}>
          Save
        </Button>
        <Button flat danger icon="delete" onClick={() => setConfirmDelete(true)}>
          Delete
        </Button>
      </div>
      <ConfirmDialog
        open={confirmDelete}
        message={`Delete preset '${preset.name}'?`}
        destructive
        confirmLabel="Delete"
        onConfirm={doDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </Expansion>
  )
}

function NewPresetForm({ byKind }: { byKind: Map<PromptBlockKind, PromptBlock[]> }) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [model, setModel] = useState(DEFAULT_GEMINI_MODEL)
  const [isDefault, setIsDefault] = useState(false)
  const [selection, setSelection] = useState<Partial<Record<PromptBlockKind, string>>>({})

  const valueFor = (kind: PromptBlockKind): string => {
    if (selection[kind]) return selection[kind]!
    const blocks = byKind.get(kind) ?? []
    return blocks.find((b) => b.is_default)?.id ?? blocks[0]?.id ?? ''
  }

  const create = async () => {
    if (!name) {
      notify('Name is required', 'warning')
      return
    }
    if (PROMPT_BLOCK_KINDS.some((kind) => !valueFor(kind))) {
      notify('All five blocks must be selected', 'warning')
      return
    }
    try {
      await api.createPromptPreset({
        name,
        model_name: model || DEFAULT_GEMINI_MODEL,
        ...Object.fromEntries(PROMPT_BLOCK_KINDS.map((kind) => [`${kind}_block_id`, valueFor(kind)])),
        is_default: isDefault,
      })
    } catch (err) {
      notify(`Create failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify('Created', 'positive')
    setName('')
    queryClient.invalidateQueries({ queryKey: ['prompt-presets'] })
  }

  return (
    <Expansion title="Add new preset" bordered>
      <TextField label="Name" value={name} onChange={setName} />
      <TextField label="Gemini model" value={model} onChange={setModel} />
      {PROMPT_BLOCK_KINDS.map((kind) => (
        <SelectField
          key={kind}
          label={kind[0].toUpperCase() + kind.slice(1)}
          value={valueFor(kind)}
          onChange={(v) => setSelection({ ...selection, [kind]: v })}
          options={(byKind.get(kind) ?? []).map((b) => ({ value: b.id, label: b.name }))}
        />
      ))}
      <Switch label="Make default" checked={isDefault} onChange={setIsDefault} />
      <div className="row">
        <Button primary icon="add" onClick={create}>
          Add preset
        </Button>
      </div>
    </Expansion>
  )
}
