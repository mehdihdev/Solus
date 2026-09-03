// SOLUSDEV-235 / EXT-05 — the zip surface the installer consumes, backed by
// yauzl. Listing exposes exactly what the installer must decide on (name,
// kind, declared size); reading is capped in bytes and streams are destroyed
// the moment they overrun, so a bomb never materializes in memory. yauzl
// itself refuses absolute, `..` and (with strictFileNames) backslash names
// while reading the central directory.
import { fromBufferPromise, type Entry, type ZipFile } from 'yauzl'

export interface ZipEntryInfo {
  readonly name: string
  readonly isDirectory: boolean
  readonly isSymlink: boolean
  readonly isEncrypted: boolean
  /** The size the central directory CLAIMS — bounded before extraction, then
   *  enforced against what actually inflates. */
  readonly declaredSize: number
}

export interface ZipArchive {
  readonly entries: readonly ZipEntryInfo[]
  /** Inflate one entry; rejects with ZipEntryTooLargeError past `cap` bytes. */
  read(name: string, cap: number): Promise<Uint8Array>
}

export type OpenZip = (bytes: Uint8Array) => Promise<ZipArchive>

/** Any failure while inflating an entry (a corrupt or lying archive). */
export class ZipReadError extends Error {}
export class ZipEntryTooLargeError extends ZipReadError {}

const S_IFMT = 0o170000
const S_IFLNK = 0o120000

function isSymlinkEntry(entry: Entry): boolean {
  const mode = entry.externalFileAttributes >>> 16
  return (mode & S_IFMT) === S_IFLNK
}

function describe(entry: Entry): ZipEntryInfo {
  return {
    name: entry.fileName,
    isDirectory: entry.fileName.endsWith('/'),
    isSymlink: isSymlinkEntry(entry),
    isEncrypted: entry.isEncrypted(),
    declaredSize: entry.uncompressedSize
  }
}

function collect(stream: NodeJS.ReadableStream, name: string, cap: number): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = []
    let total = 0
    stream.on('data', (chunk: Buffer) => {
      total += chunk.length
      if (total > cap) {
        ;(stream as unknown as { destroy(error: Error): void }).destroy(
          new ZipEntryTooLargeError(`${name} exceeds ${cap} bytes`)
        )
        return
      }
      chunks.push(chunk)
    })
    stream.on('error', (error: unknown) =>
      reject(error instanceof ZipReadError ? error : new ZipReadError(String(error)))
    )
    stream.on('end', () => resolve(new Uint8Array(Buffer.concat(chunks))))
  })
}

async function readEntry(zip: ZipFile, entry: Entry, cap: number): Promise<Uint8Array> {
  if (entry.uncompressedSize > cap)
    throw new ZipEntryTooLargeError(`${entry.fileName} declares ${entry.uncompressedSize} bytes`)
  let stream: NodeJS.ReadableStream
  try {
    stream = await zip.openReadStreamPromise(entry)
  } catch (error) {
    throw new ZipReadError(error instanceof Error ? error.message : String(error))
  }
  return collect(stream, entry.fileName, cap)
}

/** Open an in-memory archive. Rejects on anything that is not a well-formed
 *  zip with safe entry names. */
export const openZip: OpenZip = async (bytes) => {
  const zip = await fromBufferPromise(
    Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength),
    {
      lazyEntries: true,
      autoClose: false,
      validateEntrySizes: true,
      strictFileNames: true
    }
  )
  // Every entry is LISTED (a duplicate name is the installer's to refuse);
  // reads resolve to the first entry carrying the name.
  const all: Entry[] = []
  const byName = new Map<string, Entry>()
  for await (const entry of zip.eachEntry()) {
    all.push(entry)
    if (!byName.has(entry.fileName)) byName.set(entry.fileName, entry)
  }
  return {
    entries: all.map(describe),
    read: (name, cap) => {
      const entry = byName.get(name)
      return entry === undefined
        ? Promise.reject(new ZipReadError(`no entry named ${name}`))
        : readEntry(zip, entry, cap)
    }
  }
}
