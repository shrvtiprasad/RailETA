import process from "node:process";
import { configure, getTrainHistory } from "railkit";

const [trainNumber, journeyDate] = process.argv.slice(2);
const apiKey = process.env.RAILKIT_API_KEY;

if (!trainNumber || !journeyDate) {
  console.error("Usage: node fetch_history.mjs <train-number> <DD-MM-YYYY>");
  process.exit(2);
}

if (!apiKey) {
  console.error("RAILKIT_API_KEY is not configured in the environment.");
  process.exit(2);
}

try {
  configure(apiKey);
  const response = await getTrainHistory(trainNumber, journeyDate);
  process.stdout.write(JSON.stringify(response));
} catch (error) {
  // Never print the key or the complete request configuration.
  const message = error instanceof Error ? error.message : String(error);
  console.error(`RailKit request failed: ${message}`);
  process.exit(1);
}
