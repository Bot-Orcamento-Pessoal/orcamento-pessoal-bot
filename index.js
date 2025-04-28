const express = require('express');
const bodyParser = require('body-parser');
const axios = require('axios');

const app = express();
app.use(bodyParser.json());

// Informações do seu bot
const GUPSHUP_API_URL = 'https://api.gupshup.io/sm/api/v1/msg';
const API_KEY = 'sk_7b388ebe42994a0585db4a36584741cd'; // Sua API Key
const BOT_PHONE_NUMBER = '917834811114'; // Número do BOT no Gupshup (sem +)

// Rota para teste
app.get('/', (req, res) => {
    res.send('Bot Orcamento Pessoal está rodando!');
});

// Rota para receber mensagens do Gupshup
app.post('/webhook', async (req, res) => {
    const incomingMessage = req.body;

    console.log('Mensagem recebida:', JSON.stringify(incomingMessage, null, 2));

    if (incomingMessage.type === 'message' && incomingMessage.payload?.payload?.text) {
        const userPhone = incomingMessage.payload?.sender?.phone;
        const userName = incomingMessage.payload?.sender?.name;
        const userMessage = incomingMessage.payload?.payload?.text;

        console.log(`Recebido de ${userName} (${userPhone}): ${userMessage}`);

        // Mensagem que será enviada de volta
        const replyMessage = `Olá ${userName}! Você enviou: "${userMessage}". Estou aqui para te ajudar!`;

        try {
            await axios({
                method: 'POST',
                url: GUPSHUP_API_URL,
                headers: {
                    'Content-Type': 'application/json',
                    'apikey': API_KEY
                },
                data: {
                    channel: 'whatsapp',
                    source: BOT_PHONE_NUMBER,
                    destination: userPhone,
                    message: {
                        type: 'text',
                        text: replyMessage
                    },
                    src_name: 'OrcamentoPessoalBot'
                }
            });

            console.log('Resposta enviada com sucesso!');
        } catch (error) {
            console.error('Erro ao enviar resposta:', error.response?.data || error.message);
        }
    }

    res.sendStatus(200);
});

// Ouvindo na porta que o Render indicar
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Servidor rodando na porta ${PORT}`);
});
