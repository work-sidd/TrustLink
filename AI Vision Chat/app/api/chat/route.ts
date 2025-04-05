// 'use server'
// app/api/chat/route.ts

import OpenAI from "openai";
import { NextResponse } from "next/server";


// Opt out of static rendering
export const dynamic = 'force-dynamic';

const openai = new OpenAI({
  apiKey: process.env.NEXT_PUBLIC_OPENAI_API_KEY,
});

export async function POST(req: Request) {
  try {
    const { message, image } = await req.json();

    // console.log(message, image)
    // console.log("Received message:", process.env.NEXT_PUBLIC_OPENAI_API_KEY);
    if (!message || !image) {
      return NextResponse.json(
        { error: "Message and image are required" },
        { status: 400 }
      );
    }

    const response = await openai.responses.create({
      model: "gpt-4o-mini",
      input: [
          {
              role: "user",
              content: [
                  { type: "input_text", text: message },
                  {
                      type: "input_image",
                      image_url: image,
                  },
              ],
          },
      ],
  });

    return NextResponse.json({
      response: response.output_text,
    });
  } catch (error) {
    console.error("Error processing chat request:", error);
    return NextResponse.json(
      { error: "Failed to process request" },
      { status: 500 }
    );
  }
}
