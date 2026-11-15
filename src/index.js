import 'dotenv/config';
import FNLB from 'fnlb';

const token = process.env.API_TOKEN?.trim();
const botIds = (process.env.BOTS || '')
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean);

// Fail closed: never accidentally launch the entire FNLB bot pool.
if (!token) {
  throw new Error('Missing API_TOKEN. Add your FNLB API token in Render environment variables.');
}
if (botIds.length === 0) {
  throw new Error('Missing BOTS. Add the exact FNLB bot ID for ramn-_- in Render environment variables. No bots were started.');
}

const fnlb = new FNLB({
  clusterName: process.env.CLUSTER_NAME || 'RAMN Lobby'
});

const releaseChannel = process.env.RELEASE_CHANNEL === 'beta' ? 'beta' : 'stable';
const numberOfShards = Math.max(1, Number.parseInt(process.env.NUMBER_OF_SHARDS || '1', 10) || 1);
const botsPerShard = Math.max(1, Number.parseInt(process.env.BOTS_PER_SHARD || '1', 10) || 1);
const restartInterval = Math.max(60, Number.parseInt(process.env.RESTART_INTERVAL || '3600', 10) || 3600) * 1000;

async function startFNLB() {
  console.log(`Starting RAMN Lobby for ${botIds.length} selected bot(s)...`);
  await fnlb.start({
    apiToken: token,
    channel: releaseChannel,
    numberOfShards,
    botsPerShard,
    bots: botIds
  });
  console.log('FNLB cluster start requested successfully.');
}

let restarting = false;
async function restartFNLB() {
  if (restarting) return;
  restarting = true;
  try {
    console.log('Scheduled FNLB restart...');
    await fnlb.stop();
    await startFNLB();
  } catch (error) {
    console.error('FNLB restart failed:', error);
  } finally {
    restarting = false;
  }
}

process.on('SIGTERM', async () => {
  console.log('Stopping RAMN Lobby...');
  try { await fnlb.stop(); } finally { process.exit(0); }
});
process.on('SIGINT', async () => {
  console.log('Stopping RAMN Lobby...');
  try { await fnlb.stop(); } finally { process.exit(0); }
});

await startFNLB();
setInterval(restartFNLB, restartInterval);
