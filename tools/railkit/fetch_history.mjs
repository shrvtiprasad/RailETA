import { config } from "dotenv";
import { configure, getTrainHistory } from "railkit";
import { mkdir, writeFile } from "fs/promises";
import path from "path";

config({ path: "../../backend/.env" });

const apiKey = process.env.RAILKIT_API_KEY;

if (!apiKey) {
  console.error("RAILKIT_API_KEY is missing.");
  process.exit(1);
}

configure(apiKey);

const trainNumber = process.argv[2];
const journeyDate = process.argv[3];

if (!trainNumber || !journeyDate) {
  console.log(
    "Usage: node --use-system-ca fetch_history.mjs <train_number> <DD-MM-YYYY>"
  );
  process.exit(1);
}

try {
  const result = await getTrainHistory(trainNumber, journeyDate);

  if (!result.success) {
    console.error("RailKit error:", result.error);
    process.exit(1);
  }

  const outputDirectory = path.resolve(
    "../../backend/data/raw/railkit"
  );

  await mkdir(outputDirectory, { recursive: true });

  const safeDate = journeyDate.replaceAll("-", "_");

  const outputFile = path.join(
    outputDirectory,
    `${trainNumber}_${safeDate}.json`
  );

  await writeFile(
    outputFile,
    JSON.stringify(result.data, null, 2),
    "utf8"
  );

  console.log("History downloaded successfully.");
  console.log("Train:", result.data.trainNo);
  console.log("Name:", result.data.trainName);
  console.log("Journey:", result.data.journeyDate);
  console.log("Stations:", result.data.stations?.length ?? 0);
  console.log("Saved:", outputFile);
} catch (error) {
  console.error("Failed to download RailKit history.");
  console.error(error);
}