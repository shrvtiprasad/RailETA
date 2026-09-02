import { config } from "dotenv";
import { configure, getTrainHistory } from "railkit";

config({ path: "../../backend/.env" });

const apiKey = process.env.RAILKIT_API_KEY;

if (!apiKey) {
  console.error("RAILKIT_API_KEY is missing.");
  process.exit(1);
}

console.log("RailKit key loaded: true");
console.log("Key length:", apiKey.length);

configure(apiKey);

const trainNumber = "12301";
const journeyDate = "11-06-2026";

try {
  const result = await getTrainHistory(trainNumber, journeyDate);
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error("RailKit error:");
  console.error(error);
}